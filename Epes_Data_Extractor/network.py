# -*- coding: utf-8 -*-
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
from html.parser import HTMLParser


def http_get_sync(url, timeout_ms=30000, feedback=None, headers=None):
    timeout_s = timeout_ms / 1000
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) QGIS/3.x')
    req.add_header('Accept', 'application/json, application/geo+json, application/xml, */*')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        msg = f"Erreur HTTP {e.code} pour {url}"
        if feedback:
            feedback.pushWarning(msg)
        raise IOError(msg)
    except Exception as e:
        msg = f"Erreur réseau pour {url} : {e}"
        if feedback:
            feedback.pushWarning(msg)
        raise IOError(msg)


def http_get_bytes(url, timeout_ms=30000, feedback=None, headers=None):
    """Retourne les bytes bruts sans décodage — préserver l'encodage d'origine (ex. ISO-8859-1 pour GML MapServer)."""
    timeout_s = timeout_ms / 1000
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) QGIS/3.x')
    req.add_header('Accept', 'application/json, application/geo+json, application/xml, */*')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        msg = f"Erreur HTTP {e.code} pour {url}"
        if feedback:
            feedback.pushWarning(msg)
        raise IOError(msg)
    except Exception as e:
        msg = f"Erreur réseau pour {url} : {e}"
        if feedback:
            feedback.pushWarning(msg)
        raise IOError(msg)


def http_get_cas_auth(url, user, password, cas_login_url, timeout_s=120, feedback=None):
    """Auth CAS (SSO) : GET form → parse tokens cachés → POST creds → session → GET données."""

    class _FormParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.fields = {}
            self.action = None

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            if tag == 'form' and self.action is None:
                self.action = d.get('action', '')
            elif tag == 'input' and d.get('name'):
                self.fields[d['name']] = d.get('value', '')
            elif tag == 'button' and d.get('name') and d.get('type') == 'submit':
                self.fields[d['name']] = d.get('value', 'submit')

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    if feedback:
        feedback.pushInfo(f'    Service URL → {url}')

    # Étape 1 : GET le formulaire CAS
    cas_url_with_service = f"{cas_login_url}?service={urllib.parse.quote(url, safe='')}"
    get_req = urllib.request.Request(cas_url_with_service)
    get_req.add_header('User-Agent', ua)
    with opener.open(get_req, timeout=timeout_s) as resp:
        html = resp.read().decode('utf-8', errors='replace')
        get_final_url = resp.geturl()

    parser = _FormParser()
    parser.feed(html)
    form_fields = parser.fields
    form_fields['username'] = user
    form_fields['password'] = password
    form_fields.setdefault('_eventId', 'submit')
    form_fields.setdefault('geolocation', '')
    form_fields.setdefault('deviceFingerprint', '')

    form_action = parser.action or ''
    if form_action.startswith('http'):
        post_url = form_action
    elif form_action.startswith('/'):
        parsed_base = urllib.parse.urlparse(cas_login_url)
        post_url = f"{parsed_base.scheme}://{parsed_base.netloc}{form_action}"
    else:
        post_url = cas_url_with_service

    if feedback:
        hidden = [k for k in form_fields if k not in ('username', 'password')]
        feedback.pushInfo(f'    CAS tokens : {hidden}  | POST → {post_url}')

    # Étape 2 : POST identifiants
    post_data = urllib.parse.urlencode(form_fields).encode('utf-8')
    post_req = urllib.request.Request(post_url, data=post_data, method='POST')
    post_req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    post_req.add_header('User-Agent', ua)
    post_req.add_header('Referer', get_final_url)
    parsed_cas = urllib.parse.urlparse(cas_login_url)
    post_req.add_header('Origin', f"{parsed_cas.scheme}://{parsed_cas.netloc}")
    try:
        with opener.open(post_req, timeout=timeout_s) as resp:
            if feedback:
                feedback.pushInfo(f'    CAS login OK → {resp.geturl()}')
    except urllib.error.HTTPError as e:
        # Certains CAS terminent sur 400 même si le login a réussi (redirections vers domaine inaccessible).
        # On continue si des cookies de session ont été posés.
        cookies_details = [(c.name, c.domain) for c in cj]
        if feedback:
            feedback.pushInfo(f'    CAS redirect status {e.code}, cookies : {cookies_details}')
        if not cookies_details:
            body = ''
            try:
                body = e.read().decode('utf-8', errors='replace')[:500]
            except Exception:
                pass
            raise IOError(f"CAS login échoué ({e.code}), aucun cookie : {body}")

    # Étape 3 : GET données avec la session
    data_req = urllib.request.Request(url)
    data_req.add_header('Accept', 'application/json, application/geo+json, */*')
    data_req.add_header('User-Agent', ua)
    try:
        with opener.open(data_req, timeout=timeout_s) as resp:
            return resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        body_err = ''
        try:
            body_err = e.read().decode('utf-8', errors='replace')[:800]
        except Exception:
            pass
        msg = f"Erreur HTTP {e.code} pour {url}"
        if feedback:
            feedback.pushWarning(msg)
            if body_err:
                feedback.pushInfo(f"    Réponse serveur : {body_err}")
        raise IOError(msg)
