import streamlit as st
import datetime
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
import re

st.set_page_config(page_title="TH Taktinen Tutka", page_icon="🚕", layout="wide")

# ── 1. TIETOTURVA JA KIRJAUTUMINEN ───────────────────────────────────────────

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "2026")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; color: #5bc0de;'>🔒 TH Taktinen Tutka</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #aaa;'>Kirjaudu sisään nähdäksesi operatiivisen näkymän.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        pwd = st.text_input("Salasana", type="password")
        if st.button("Kirjaudu", use_container_width=True):
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Väärä salasana.")
    st.stop() 

# ── 2. ARKKITEHTUURIN PERUSTA: API-AVAIMET JA TILA ───────────────────────────

FINAVIA_API_KEY = st.secrets.get("FINAVIA_API_KEY", "c24ac18c01e44b6e9497a2a3034182ef")

if "valittu_asema" not in st.session_state:
    st.session_state.valittu_asema = "Helsinki"

st.markdown("""
<style>
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
.main { background-color: #121212; }
.header-container {
    display: flex; justify-content: space-between; align-items: flex-start;
    border-bottom: 1px solid #333; padding-bottom: 15px; margin-bottom: 20px;
}
.app-title { font-size: 32px; font-weight: bold; color: #ffffff; margin-bottom: 5px; }
.time-display { font-size: 42px; font-weight: bold; color: #e0e0e0; line-height: 1; }
.taksi-card {
    background-color: #1e1e2a; color: #e0e0e0; padding: 22px;
    border-radius: 12px; margin-bottom: 20px; font-size: 20px;
    border: 1px solid #3a3a50; box-shadow: 0 4px 8px rgba(0,0,0,0.3); line-height: 1.7;
}
.card-title {
    font-size: 24px; font-weight: bold; margin-bottom: 12px;
    color: #ffffff; border-bottom: 2px solid #444; padding-bottom: 8px;
}
.taksi-link {
    color: #5bc0de; text-decoration: none; font-size: 18px;
    display: inline-block; margin-top: 12px; font-weight: bold;
}
.badge-red    { background:#7a1a1a; color:#ff9999; padding:2px 8px; border-radius:4px; font-size:16px; font-weight:bold; }
.badge-yellow { background:#5a4a00; color:#ffeb3b; padding:2px 8px; border-radius:4px; font-size:16px; font-weight:bold; }
.badge-green  { background:#1a4a1a; color:#88d888; padding:2px 8px; border-radius:4px; font-size:16px; font-weight:bold; }
.badge-blue   { background:#1a2a5a; color:#8ab4f8; padding:2px 8px; border-radius:4px; font-size:16px; font-weight:bold; }
.sold-out  { color: #ff4b4b; font-weight: bold; }
.pax-good  { color: #ffeb3b; font-weight: bold; }
.pax-ok    { color: #a3c2a3; }
.delay-bad { color: #ff9999; font-weight: bold; }
.on-time   { color: #88d888; }
.section-header {
    color: #e0e0e0; font-size: 24px; font-weight: bold;
    margin-top: 28px; margin-bottom: 10px;
    border-left: 4px solid #5bc0de; padding-left: 12px;
}
.venue-name { color: #ffffff; font-weight: bold; }
.venue-address { color: #aaaaaa; font-size: 16px; }
.endtime { color: #ffeb3b; font-size: 15px; font-weight: bold; }
.eventline { border-left: 3px solid #333; padding-left: 12px; margin-bottom: 16px; }
.live-event { color: #88d888; font-weight: bold; }
.no-event { color: #888888; font-style: italic; }
</style>
""", unsafe_allow_html=True)

# ── 3. HEURISTIIKKAMOOTTORI ───────────────────────────────────────────

def laske_kysyntakerroin(wb_status, klo_str):
    indeksi = 2.0 
    if wb_status: indeksi += 5.0
    try:
        tunnit = int(klo_str.split(":")[0])
        if tunnit >= 22 or tunnit <= 4: indeksi += 2.5
        elif 15 <= tunnit <= 18: indeksi += 1.5
    except: pass
    indeksi = min(indeksi, 10.0)
    
    if indeksi >= 7: return f"<span style='color:#ff4b4b; font-weight:bold;'>🔥 Kysyntä: {indeksi}/10</span>"
    elif indeksi >= 4: return f"<span style='color:#ffeb3b;'>⚡ Kysyntä: {indeksi}/10</span>"
    else: return f"<span style='color:#a3c2a3;'>Kysyntä: {indeksi}/10</span>"

# ── HAKUFUNKTIOT (CACHE) ──────────────────────────────────────────────────────

@st.cache_data(ttl=86400)
def hae_juna_asemat():
    asemat = {
        "HKI": "Helsinki", "PSL": "Pasila", "TKL": "Tikkurila", "KRS": "Kerava", "JRV": "Järvenpää",
        "RHI": "Riihimäki", "HML": "Hämeenlinna", "TPE": "Tampere", "TKU": "Turku", "TKA": "Turku satama",
        "POR": "Pori", "VAA": "Vaasa", "SEI": "Seinäjoki", "YV": "Ylivieska", "KOK": "Kokkola",
        "OUL": "Oulu", "KEM": "Kemi", "ROV": "Rovaniemi", "KLI": "Kolari", "KJA": "Kajaani",
        "KUO": "Kuopio", "JNS": "Joensuu", "ILO": "Iisalmi", "MIK": "Mikkeli", "KV": "Kouvola",
        "LPR": "Lappeenranta", "IMR": "Imatra", "PMI": "Parikkala", "LH": "Lahti", "KTK": "Kotka",
        "VNA": "Vainikkala", "VKO": "Vainikkala", "MÄ": "Mäntsälä", "LAE": "Lappila", "MN": "Mäntyharju",
        "KAU": "Kauhava", "LAP": "Lapua", "VTI": "Vihanti", "YST": "Ylistaro", "KRN": "Karjaa"
    }
    try:
        resp = requests.get("https://rata.digitraffic.fi/api/v1/metadata/stations", timeout=10)
        resp.raise_for_status()
        for s in resp.json(): asemat[s["stationShortCode"]] = s["stationName"].replace(" asema", "")
    except: pass
    return asemat

@st.cache_data(ttl=600)
def get_averio_ships():
    laivat = []
    try:
        resp = requests.get("https://averio.fi/laivat", headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for taulu in soup.find_all("table"):
            for rivi in taulu.find_all("tr"):
                solut = [td.get_text(strip=True) for td in rivi.find_all(["td", "th"])]
                if len(solut) < 3: continue
                rivi_teksti = " ".join(solut).lower()
                if any(h in rivi_teksti for h in ["alus", "laiva", "ship", "vessel"]): continue
                pax = None
                for solu in solut:
                    puhdas = re.sub(r"[^\d]", "", solu)
                    if puhdas and 50 <= int(puhdas) <= 9999:
                        pax = int(puhdas); break
                nimi_kandidaatit = [s for s in solut if re.search(r"[A-Za-zÀ-ÿ]{3,}", s)]
                if not nimi_kandidaatit: continue
                nimi = max(nimi_kandidaatit, key=len)
                laivat.append({
                    "ship": nimi, "terminal": _tunnista_terminaali(rivi_teksti),
                    "time": _etsi_aika(solut), "pax": pax,
                })
        return laivat[:5] if laivat else [{"ship": "Averio: HTML-rakenne muuttunut", "terminal": "Tarkista", "time": "-", "pax": None}]
    except Exception as e: return [{"ship": f"Averio-virhe: {e}", "terminal": "-", "time": "-", "pax": None}]

def _tunnista_terminaali(teksti):
    if "t2" in teksti or "lansisatama" in teksti or "länsisatama" in teksti: return "Länsisatama T2"
    if "t1" in teksti or "olympia" in teksti: return "Olympia T1"
    if "katajanokka" in teksti: return "Katajanokka"
    if "vuosaari" in teksti: return "Vuosaari (rahti)"
    return "Tarkista"

def _etsi_aika(osat):
    for osa in osat:
        m = re.search(r"\b([0-2]?\d:[0-5]\d)\b", str(osa))
        if m: return m.group(1)
    return "-"

def _pax_arvio(pax):
    if pax is None: return "Ei tietoa", "pax-ok"
    autoa = round(pax * 0.025)
    if pax >= 1500: return f"🔥 {pax} matkustajaa (~{autoa} autoa, HYVÄ)", "pax-good"
    if pax >= 800: return f"✅ {pax} matkustajaa (~{autoa} autoa, NORMAALI)", "pax-ok"
    return f"⬇️ {pax} matkustajaa (~{autoa} autoa, HILJAINEN)", "pax-ok"

@st.cache_data(ttl=600)
def get_port_schedule():
    try:
        resp = requests.get("https://www.portofhelsinki.fi/matkustajille/matkustajatietoa/lahtevat-ja-saapuvat-matkustajalaivat/#tabs-2", headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        resp.raise_for_status()
        lista = []
        for rivi in BeautifulSoup(resp.text, "html.parser").find_all("tr"):
            solut = rivi.find_all("td")
            if len(solut) >= 4:
                aika = solut[0].get_text(strip=True)
                laiva = solut[1].get_text(strip=True)
                terminaali = solut[3].get_text(strip=True) if len(solut) > 3 else "?"
                if aika and laiva and re.match(r"\d{1,2}:\d{2}", aika):
                    lista.append({"time": aika, "ship": laiva, "terminal": terminaali})
        return lista[:6] if lista else []
    except: return []

@st.cache_data(ttl=50)
def get_trains(asema_nimi):
    nykyhetki = datetime.datetime.now(ZoneInfo("Europe/Helsinki"))
    koodi = {"Helsinki": "HKI", "Pasila": "PSL", "Tikkurila": "TKL"}.get(asema_nimi, "HKI")
    asemat_dict = hae_juna_asemat()
    tulos = []
    try:
        resp = requests.get(f"https://rata.digitraffic.fi/api/v1/live-trains/station/{koodi}?arrived_trains=0&arriving_trains=25&train_categories=Long-distance", timeout=10)
        resp.raise_for_status()
        for juna in resp.json():
            if juna.get("cancelled"): continue
            nimi = f"{juna.get('trainType', '')} {juna.get('trainNumber', '')}"
            lahto_koodi = next((r["stationShortCode"] for r in juna["timeTableRows"] if r["type"] == "DEPARTURE"), juna["timeTableRows"][0]["stationShortCode"])
            if lahto_koodi in ("HKI", "PSL", "TKL", "ILA", "KRS"): continue
            
            aika_obj = aika_str = None
            viive = 0
            for rivi in juna["timeTableRows"]:
                if rivi["stationShortCode"] == koodi and rivi["type"] == "ARRIVAL":
                    raaka = rivi.get("liveEstimateTime") or rivi.get("scheduledTime", "")
                    try:
                        aika_obj = datetime.datetime.strptime(raaka[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo("Europe/Helsinki"))
                        if aika_obj < nykyhetki - datetime.timedelta(minutes=3): continue
                        aika_str = aika_obj.strftime("%H:%M")
                    except: pass
                    viive = rivi.get("differenceInMinutes", 0)
                    break
            if aika_str and aika_obj: tulos.append({"train": nimi, "origin": asemat_dict.get(lahto_koodi, lahto_koodi), "time": aika_str, "dt": aika_obj, "delay": max(viive, 0)})
        tulos.sort(key=lambda k: k["dt"])
        return tulos[:6]
    except Exception as e: return [{"train": "API-virhe", "origin": str(e)[:40], "time": "-", "dt": None, "delay": 0}]

@st.cache_data(ttl=60)
def get_flights():
    laajarunko = {"359", "350", "333", "330", "340", "788", "789", "777", "77W", "388", "744", "74H"}
    endpoints = [
        (f"https://apigw.finavia.fi/flights/public/v0/flights/arr/HEL?subscription-key={FINAVIA_API_KEY}", {}),
        ("https://apigw.finavia.fi/flights/public/v0/flights/arr/HEL", {"Ocp-Apim-Subscription-Key": FINAVIA_API_KEY}),
    ]
    for url, extra_headers in endpoints:
        hdrs = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Cache-Control": "no-cache"}
        hdrs.update(extra_headers)
        try:
            resp = requests.get(url, headers=hdrs, timeout=10)
            if resp.status_code in (401, 403): continue
            resp.raise_for_status()
            data = resp.json()
            saapuvat = []
            if isinstance(data, list): saapuvat = data
            elif isinstance(data, dict):
                for avain in ("arr", "flights", "body"):
                    if isinstance(data.get(avain), list): saapuvat = data[avain]; break
                if not saapuvat and isinstance(data.get("body"), dict):
                    for ala in ("arr", "flight"):
                        if isinstance(data["body"].get(ala), list): saapuvat = data["body"][ala]; break
            if not saapuvat: continue
            
            tulos = []
            for lento in saapuvat:
                actype = str(lento.get("actype") or lento.get("aircraftType", ""))
                status = str(lento.get("prt_f") or lento.get("statusInfo", "Odottaa"))
                aika_r = str(lento.get("sdt") or lento.get("scheduledTime", ""))
                wb = any(c in actype for c in laajarunko)
                if wb and "laskeutunut" not in status.lower() and "landed" not in status.lower(): status = f"🔥 Odottaa massapurkua – {status}"
                elif "delay" in status.lower() or "myohassa" in status.lower(): status = f"🔴 {status}"
                
                tulos.append({
                    "flight": lento.get("fltnr") or lento.get("flightNumber", "??"),
                    "origin": lento.get("route_n_1") or lento.get("airport", "Tuntematon"),
                    "time": aika_r[11:16] if "T" in aika_r else aika_r[:5],
                    "type": f"Laajarunko (✈ {actype})" if wb else f"Kapearunko ({actype})",
                    "wb": wb, "status": status
                })
            tulos.sort(key=lambda x: (not x["wb"], x["time"]))
            return tulos[:8], None
        except: continue
    return [], "Finavia API ei vastannut. Tarkista avain."

@st.cache_data(ttl=3600)
def get_culture_live_events():
    live_tapahtumat = {}
    try:
        now = datetime.datetime.now(ZoneInfo("Europe/Helsinki"))
        url = f"https://linkedevents.api.hel.fi/v1/event/?start={now.replace(hour=0, minute=0, second=0).isoformat()}&include=location"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        for e in resp.json().get("data", []):
            paikka_nimi = (e.get("location", {}).get("name", {}).get("fi") or "").lower()
            end_time_str = e.get("end_time")
            if not end_time_str or not paikka_nimi: continue
            try:
                end_dt = datetime.datetime.fromisoformat(end_time_str.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Helsinki"))
                if end_dt > now and end_dt.date() == now.date():
                    if paikka_nimi not in live_tapahtumat: live_tapahtumat[paikka_nimi] = []
                    live_tapahtumat[paikka_nimi].append(f"{e.get('name', {}).get('fi', 'Tuntematon esitys')} ({end_dt.strftime('%H:%M')})")
            except: pass
    except: pass
    return live_tapahtumat

def yhdista_kulttuuridata(paikat):
    live_data = get_culture_live_events()
    for p in paikat:
        hakusanat = p.get("hakusanat", [])
        loydetty_live = False
        for api_paikka, tapahtumat in live_data.items():
            if any(sana in api_paikka for sana in hakusanat):
                p["lopetus_html"] = f"<span class='live-event'>🟢 LIVE TÄNÄÄN: {' | '.join(tapahtumat)}</span>"
                loydetty_live = True; break
        if not loydetty_live:
            if hakusanat: p["lopetus_html"] = f"<span class='no-event'>⚪ Ei julkista esitystä tänään API:ssa.</span><br><span style='color:#777;'>Tyypillisesti: {p['lopetus']}</span>"
            else: p["lopetus_html"] = f"<span class='endtime'>⏱ Tyypillinen lopetus: {p['lopetus']}</span>"
    return paikat

@st.cache_data(ttl=3600)
def get_general_live_events():
    tulos = []
    try:
        now = datetime.datetime.now(ZoneInfo("Europe/Helsinki"))
        resp = requests.get("https://linkedevents.api.hel.fi/v1/event/?start=now&sort=end_time&include=location", timeout=10)
        resp.raise_for_status()
        for e in resp.json().get("data", []):
            end_time_str = e.get("end_time")
            if not end_time_str: continue
            try:
                end_dt = datetime.datetime.fromisoformat(end_time_str.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Helsinki"))
                if end_dt > now and end_dt.date() == now.date() and end_dt.hour >= 16:
                    loc = e.get("location", {})
                    osoite = loc.get("name", {}).get("fi") or loc.get("street_address", {}).get("fi") or "Helsinki"
                    tulos.append({"nimi": e.get("name", {}).get("fi", "Tuntematon tapahtuma"), "loppu": end_dt.strftime("%H:%M"), "paikka": osoite, "dt": end_dt})
            except: pass
        tulos.sort(key=lambda x: x["dt"])
        return tulos[:10]
    except: return []

def viive_badge(minuutit):
    if minuutit <= 0: return "<span class='badge-green'>Aikataulussa</span>"
    if minuutit < 15: return f"<span class='badge-yellow'>+{minuutit} min</span>"
    if minuutit < 60: return f"<span class='badge-red'>⚠ +{minuutit} min</span>"
    return f"<span class='badge-red'>🚨 +{minuutit} min – VR-korvaus!</span>"

def venue_card(p):
    lopetus_naytto = p.get('lopetus_html', f"<span class='endtime'>⏱ Tyypillinen lopetus: {p['lopetus']}</span>")
    card_html = f"<div class='eventline'><span class='{p['badge']}'>●</span> <span class='venue-name'>{p['nimi']}</span><br><span class='venue-address'>Max pax: <b>{p['kap']}</b></span><br><span style='color:#ccc;font-size:17px;'>{p['huomio']}</span><br>{lopetus_naytto}<br><a href='{p['linkki']}' class='taksi-link' target='_blank' style='font-size:16px;'>{p['teksti']} →</a>"
    if 'linkki2' in p: card_html += f" &nbsp;&nbsp;|&nbsp;&nbsp; <a href='{p['linkki2']}' class='taksi-link' target='_blank' style='font-size:16px;'>{p['teksti2']} →</a>"
    return card_html + "</div>"

# ── 4. DASHBOARD (NATIIVI AUTOREFRESH) ───────────────────────────────────────

# UUSI OMINAISUUS: Tämä decorator pakottaa vain tämän funktion piirtymään uusiksi 300 sekunnin välein
@st.fragment(run_every=300)
def render_dashboard():
    suomen_aika = datetime.datetime.now(ZoneInfo("Europe/Helsinki"))
    klo   = suomen_aika.strftime("%H:%M")
    paiva = suomen_aika.strftime("%a %d.%m.%Y").capitalize()
    HSL_LINKKI = "https://www.hsl.fi/matkustaminen/liikenne?language=fi&page=1&validityPeriod=true&transportMode=1&transportMode=2&transportMode=4&transportMode=3&transportMode=5&transportMode=6&favouritesOnly=false"

    st.markdown(f"""
    <div class='header-container'>
      <div>
        <div class='app-title'>🚕 TH Taktinen Tutka</div>
        <div class='time-display'>{klo} <span style='font-size:16px;color:#888;'>Helsinki – {paiva}</span></div>
      </div>
      <div style='text-align:right;'>
        <a href='https://www.ilmatieteenlaitos.fi/sade-ja-pilvialueet?area=etela-suomi' class='taksi-link' target='_blank' style='font-size:22px;'>🌧 Sadetutka &#x2192;</a><br>
        <a href='https://liikennetilanne.fintraffic.fi/?x=385557.5&y=6672322.0&z=10' class='taksi-link' target='_blank' style='font-size:18px;'>🗺 Liikennetilanne &#x2192;</a><br>
        <a href='{HSL_LINKKI}' class='taksi-link' target='_blank' style='font-size:18px;'>🚇 HSL-häiriöt &#x2192;</a>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # LOHKO 1: JUNAT
    st.markdown("<div class='section-header'>🚆 SAAPUVAT KAUKOJUNAT</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    if c1.button("Helsinki (HKI)", use_container_width=True): st.session_state.valittu_asema = "Helsinki"
    if c2.button("Pasila (PSL)", use_container_width=True): st.session_state.valittu_asema = "Pasila"
    if c3.button("Tikkurila (TKL)", use_container_width=True): st.session_state.valittu_asema = "Tikkurila"

    valittu = st.session_state.valittu_asema
    junat = get_trains(valittu)
    vr_linkit = {
        "Helsinki": "https://www.vr.fi/radalla?station=HKI&direction=ARRIVAL&stationFilters=%7B%22trainCategory%22%3A%22Long-distance%22%7D&follow=true",
        "Pasila": "https://www.vr.fi/radalla?station=PSL&direction=ARRIVAL&stationFilters=%7B%22trainCategory%22%3A%22Long-distance%22%7D",
        "Tikkurila": "https://www.vr.fi/radalla?station=TKL&direction=ARRIVAL&stationFilters=%7B%22trainCategory%22%3A%22Long-distance%22%7D&follow=true",
    }
    
    juna_html = f"<span style='color:#aaa;font-size:17px;'>Asema: <b>{valittu}</b> – vain kaukoliikenne</span><br><br>"
    if junat and junat[0]["train"] != "API-virhe":
        for j in junat: juna_html += f"<b>{j['time']}</b>  ·  {j['train']} <span style='color:#aaa;'>(lähtö: {j['origin']}{' ⭐' if j['origin'] in {'Rovaniemi', 'Kolari', 'Kemi', 'Oulu', 'Kajaani', 'Kuopio', 'Joensuu', 'Iisalmi', 'Ylivieska'} else ''})</span><br>  └ {viive_badge(j['delay'])}<br><br>"
    else: juna_html += "Ei saapuvia kaukojunia lähiaikoina."

    st.markdown(f"<div class='taksi-card'>{juna_html}<a href='{vr_linkit[valittu]}' class='taksi-link' target='_blank'>VR Live ({valittu}) &#x2192;</a> &nbsp;&nbsp; <a href='https://www.vr.fi/radalla/poikkeustilanteet' class='taksi-link' target='_blank' style='color:#ff9999;'>⚠ VR Poikkeukset &#x2192;</a></div>", unsafe_allow_html=True)

    # LOHKO 2: LAIVAT
    st.markdown("<div class='section-header'>🚢 MATKUSTAJALAIVAT</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    with col_a:
        averio_html = "<div class='card-title'>Averio – Matkustajamäärät</div><span style='color:#aaa;font-size:15px;'>⚠ klo 00:30 MS Finlandia → <b>Länsisatama T2</b>, ei Vuosaari</span><br><br>"
        for laiva in get_averio_ships():
            arvio_teksti, arvio_css = _pax_arvio(laiva["pax"])
            averio_html += f"<b>{laiva['time']}</b>  ·  {laiva['ship']}<br>  └ Terminaali: {laiva['terminal']}<br>  └ <span class='{arvio_css}'>{arvio_teksti}</span><br><br>"
        st.markdown(f"<div class='taksi-card'>{averio_html}<a href='https://averio.fi/laivat' class='taksi-link' target='_blank'>Avaa Averio →</a></div>", unsafe_allow_html=True)
    with col_b:
        port_html = "<div class='card-title'>Helsingin Satama – Aikataulu</div>"
        port_laivat = get_port_schedule()
        if port_laivat:
            for laiva in port_laivat: port_html += f"<b>{laiva['time']}</b>  ·  {laiva['ship']}<br>  └ {laiva['terminal']}<br><br>"
        else: port_html += "Ei dataa – sivu vaatii JavaScript-renderöinnin.<br>"
        st.markdown(f"<div class='taksi-card'>{port_html}<a href='https://www.portofhelsinki.fi/matkustajille/matkustajatietoa/lahtevat-ja-saapuvat-matkustajalaivat/#tabs-2' class='taksi-link' target='_blank'>Helsingin Satama →</a></div>", unsafe_allow_html=True)

    # LOHKO 3: LENNOT
    st.markdown("<div class='section-header'>✈️ LENTOKENTTÄ (Helsinki-Vantaa)</div>", unsafe_allow_html=True)
    lennot, lento_virhe = get_flights()
    if lento_virhe: st.markdown(f"<div class='taksi-card'><div class='card-title'>Finavia API</div><span style='color:#ff9999;'>⚠ {lento_virhe}</span><br><br><a href='https://www.finavia.fi/fi/lentoasemat/helsinki-vantaa/lennot?tab=arr' class='taksi-link' target='_blank'>Finavia – Saapuvat lennot →</a></div>", unsafe_allow_html=True)
    else:
        lento_html = "<div class='card-title'>Taktiset poiminnat – saapuvat</div><span style='color:#aaa;font-size:15px;'>Frankfurt arki-iltaisin = paras business-lento | Sähköautoilla tolppaetuoikeus</span><br><br>"
        for lento in lennot: lento_html += f"<b>{lento['time']}</b>  ·  {lento['origin']} <span style='color:#aaa;'>({lento['flight']})</span><br>  └ <span class='{'pax-good' if lento['wb'] else 'pax-ok'}'>{lento['type']}</span> | {lento['status']}<br>  └ {laske_kysyntakerroin(lento['wb'], lento['time'])}<br><br>"
        st.markdown(f"<div class='taksi-card'>{lento_html}<a href='https://www.finavia.fi/fi/lentoasemat/helsinki-vantaa/lennot?tab=arr' class='taksi-link' target='_blank'>Finavia Saapuvat →</a></div>", unsafe_allow_html=True)

    # LOHKO 4: TAPAHTUMAT
    st.markdown("<div class='section-header'>📅 TAPAHTUMAT & KAPASITEETTI</div>", unsafe_allow_html=True)
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Kulttuuri & VIP", "Urheilu", "Messut & Arenat", "Musiikki", "🔴 Yleiset (Live)"])
    with tab1: st.markdown(f"<div class='taksi-card'>{''.join(venue_card(p) for p in yhdista_kulttuuridata([{'nimi': 'Helsingin Kaupunginteatteri (HKT)', 'kap': '947 hlö', 'hakusanat': ['kaupunginteatteri', 'hkt'], 'huomio': 'Paras yksittäinen kohde. Eläintarha.', 'lopetus': 'klo 21:30–22:30', 'linkki': 'https://hkt.fi/kalenteri/', 'teksti': 'HKT Kalenteri', 'badge': 'badge-red'}, {'nimi': 'Kansallisooppera ja -baletti', 'kap': '1 700 hlö', 'hakusanat': ['ooppera', 'baletti'], 'huomio': 'Ooppera = parhaat kyydit. Töölönlahti.', 'lopetus': 'klo 21:00–23:00', 'linkki': 'https://oopperabaletti.fi/kalenteri/', 'teksti': 'Ooppera Ohjelmisto', 'badge': 'badge-yellow'}, {'nimi': 'Kansallisteatteri', 'kap': '1 000 hlö', 'hakusanat': ['kansallisteatteri'], 'huomio': 'Aseman vieressä, Rautatientori.', 'lopetus': 'klo 21:00–22:30', 'linkki': 'https://www.kansallisteatteri.fi/ohjelmisto/ohjelmistokalenteri', 'teksti': 'Kansallisteatteri Kalenteri', 'badge': 'badge-blue'}, {'nimi': 'Musiikkitalo', 'kap': '1 704 hlö', 'hakusanat': ['musiikkitalo'], 'huomio': 'Mannerheimintie.', 'lopetus': 'klo 21:00–22:30', 'linkki': 'https://musiikkitalo.fi/tapahtumat/', 'teksti': 'Musiikkitalo Tapahtumat', 'badge': 'badge-blue'}, {'nimi': 'Tanssin talo (Kaapelitehdas)', 'kap': '1 000 hlö', 'hakusanat': ['tanssin talo', 'kaapelitehdas'], 'huomio': 'Modernin tanssin keskus. Erkko-sali 700 hlö, Pannuhalli 235 hlö.', 'lopetus': 'klo 21:00–22:30', 'linkki': 'https://www.tanssintalo.fi/ohjelma', 'teksti': 'Tanssin talo Kalenteri', 'badge': 'badge-blue'}, {'nimi': 'Helsingin Suomalainen Klubi', 'kap': '300 hlö', 'hakusanat': [], 'huomio': 'Yritysjohto – pitkät iltakyydit arki-iltaisin. Kamppi.', 'lopetus': 'klo 22:00–01:00', 'linkki': 'https://tapahtumat.klubi.fi/tapahtumat/', 'teksti': 'Klubi Tapahtumat', 'badge': 'badge-red'}, {'nimi': 'Svenska Klubben', 'kap': '200 hlö', 'hakusanat': [], 'huomio': 'Korkeaprofiilinen – erityisseuranta tapahtumailtaisin. Kruununhaka.', 'lopetus': 'klo 22:00–01:00', 'linkki': 'https://klubben.fi/start/program/', 'teksti': 'Svenska Klubben Ohjelma', 'badge': 'badge-red'}, {'nimi': 'Finlandia-talo', 'kap': '1 700 hlö', 'hakusanat': ['finlandia-talo', 'pikku-finlandia'], 'huomio': 'Kongressit ja gaalat. Hyvä yrityspoistumat iltaisin.', 'lopetus': 'klo 21:00–23:00', 'linkki': 'https://finlandiatalo.fi/finlandia-talo/tulevat-tapahtumat/', 'teksti': 'Finlandia-talo Kalenteri', 'badge': 'badge-yellow'}]))}</div>", unsafe_allow_html=True)
    with tab2: st.markdown(f"<div class='taksi-card'>{''.join(venue_card(p) for p in [{'nimi': 'HIFK – Nordis (jääkiekko)', 'kap': '8 200 hlö', 'huomio': 'Paras seura kyytien kannalta. Poistumapiikki ~2,5 h kiekon jälkeen.', 'lopetus': 'klo 21:30–23:00 (60+60+20 min + mahdolliset jatkoajat)', 'linkki': 'https://liiga.fi/fi/ohjelma?kausi=2025-2026&sarja=runkosarja&joukkue=hifk&kotiVieras=koti', 'teksti': 'HIFK Kotiottelut', 'badge': 'badge-red'}, {'nimi': 'Kiekko-Espoo – Metro Areena', 'kap': '8 500 hlö', 'huomio': 'Suurin areena. Kyydit myös Espoosta Helsinkiin.', 'lopetus': 'klo 21:30–23:00', 'linkki': 'https://liiga.fi/fi/ohjelma?kausi=2025-2026&sarja=runkosarja&joukkue=k-espoo&kotiVieras=koti', 'teksti': 'Kiekko-Espoo Kotiottelut', 'badge': 'badge-yellow'}, {'nimi': 'Veikkaus Arena (Jokerit & Tapahtumat)', 'kap': '15 000 hlö', 'huomio': 'Jokereiden kotiottelut ja suurtapahtumat. Valtava poistumapiikki.', 'lopetus': 'klo 21:00–22:30 (jääkiekko), 23:00 (konsertit)', 'linkki': 'https://www.veikkausarena.fi/fi/all-events', 'teksti': 'Veikkaus Arena Tapahtumat', 'badge': 'badge-red'}, {'nimi': 'Bolt Arena (HJK)', 'kap': '10 770 hlö', 'huomio': 'Veikkausliiga ja HJK kotiottelut. Töölö. Huono sää nostaa kyytikerrointa.', 'lopetus': 'klo 21:00–22:30 (45+45+lisäaika)', 'linkki': 'https://www.hjk.fi/ottelut/miehet/', 'teksti': 'HJK Otteluohjelma', 'badge': 'badge-blue'}, {'nimi': 'Olympiastadion (jalkapallo / tapahtumat)', 'kap': '50 000 hlö', 'huomio': 'Maaottelut, konsertit. Suuri poistumapiikki.', 'lopetus': 'klo 21:30–23:30 (konserteilla myöhemmin)', 'linkki': 'https://olympiastadion.fi/tapahtumat', 'teksti': 'Olympiastadion Tapahtumat', 'badge': 'badge-red'}])}</div>", unsafe_allow_html=True)
    with tab3: st.markdown(f"<div class='taksi-card'>{''.join(venue_card(p) for p in [{'nimi': 'Messukeskus', 'kap': '50 000 hlö', 'huomio': 'Poistumapiikki oviensulkemisaikaan – EI alkamisaikaan! Pasila.', 'lopetus': 'Sulkeutuu klo 17:00–18:00 (messut) tai 23:00 (konsertit)', 'linkki': 'https://messukeskus.com/kavijalle/tapahtumat/tapahtumakalenteri/', 'teksti': 'Messukeskus Kalenteri', 'badge': 'badge-red'}, {'nimi': 'Aalto-yliopisto / Dipoli (Espoo)', 'kap': '1 000 hlö', 'huomio': 'Kansainväliset kongressit. Business-asiakkaat, pitkät kyydit.', 'lopetus': 'klo 17:00–21:00', 'linkki': 'https://www.dipoli.fi/fi/', 'teksti': 'Dipoli Info', 'badge': 'badge-yellow'}, {'nimi': 'Kalastajatorppa / Pyöreä Sali', 'kap': '500 hlö', 'huomio': 'Business-illalliset. Pitkät kyydit kantakaupunkiin.', 'lopetus': 'klo 22:00–00:00', 'linkki': 'https://kalastajatorppa.fi/tapahtumat/', 'teksti': 'Kalastajatorppa Tapahtumat', 'badge': 'badge-yellow'}, {'nimi': 'Helsingin alueen yleiskalenterit', 'kap': 'Koko kaupunki', 'huomio': 'Paras yleissilmäys kaikista kaupungin tapahtumista.', 'lopetus': 'Vaihtelee', 'linkki': 'https://stadissa.fi/', 'teksti': 'Stadissa.fi', 'linkki2': 'https://www.myhelsinki.fi/fi/tapahtumat', 'teksti2': 'MyHelsinki Tapahtumat', 'badge': 'badge-blue'}])}</div>", unsafe_allow_html=True)
    with tab4: st.markdown(f"<div class='taksi-card'>{''.join(venue_card(p) for p in [{'nimi': 'Tavastia', 'kap': '900 hlö', 'huomio': 'Paras keikkapaikka kyytien kannalta.', 'lopetus': 'klo 22:30–01:00', 'linkki': 'https://tavastiaklubi.fi/', 'teksti': 'Tavastia Ohjelma', 'badge': 'badge-yellow'}, {'nimi': 'On the Rocks', 'kap': '600 hlö', 'huomio': 'Rock, metal. Tarkista täyttöaste ennen siirtymistä.', 'lopetus': 'klo 22:00–01:00', 'linkki': 'https://www.rocks.fi/tapahtumat/', 'teksti': 'On the Rocks Ohjelma', 'badge': 'badge-yellow'}, {'nimi': 'Kulttuuritalo', 'kap': '1 500 hlö', 'huomio': 'Isommat rock-konsertit. Hyvä kyytipotentiaali.', 'lopetus': 'klo 22:00–00:00', 'linkki': 'https://kulttuuritalo.fi/tapahtumat/', 'teksti': 'Kulttuuritalo Tapahtumat', 'badge': 'badge-yellow'}, {'nimi': 'Malmitalo', 'kap': '400 hlö', 'huomio': 'Iskelmä, kansanmusiikki. Kauempana – hyvä päivävuoroille.', 'lopetus': 'klo 21:00–22:30', 'linkki': 'https://www.malmitalo.fi/', 'teksti': 'Malmitalo Tapahtumat', 'badge': 'badge-blue'}, {'nimi': 'Sellosali (Espoo)', 'kap': '400 hlö', 'huomio': 'Klassinen, jazz. Pitkä kyyti kantakaupunkiin.', 'lopetus': 'klo 21:00–22:00', 'linkki': 'https://www.espoo.fi/fi/sellosalin-tapahtumat', 'teksti': 'Sellosali Ohjelma', 'badge': 'badge-blue'}, {'nimi': 'Flow Festival / Suvilahdentie', 'kap': '30 000 hlö / päivä', 'huomio': 'Kesäfestivaalit (elokuu). Erittäin suuri poistumapiikki illalla.', 'lopetus': 'klo 23:00–01:00', 'linkki': 'https://www.flowfestival.com/ohjelma/', 'teksti': 'Flow Festival Ohjelma', 'badge': 'badge-red'}])}</div>", unsafe_allow_html=True)
    with tab5:
        general_tapahtumat = get_general_live_events()
        st.markdown("<div class='card-title'>Muita yleisötapahtumia (Helsinki API)</div>", unsafe_allow_html=True)
        if general_tapahtumat: st.markdown(f"<div class='taksi-card'>{''.join(f'<div class=\"eventline\"><span class=\"badge-blue\">LIVE</span> <span class=\"venue-name\">{t[\"nimi\"]}</span><br><span class=\"venue-address\">📍 {t[\"paikka\"]}</span><br><span class=\"endtime\">⏱ Päättyy: klo {t[\"loppu\"]}</span></div>' for t in general_tapahtumat)}</div>", unsafe_allow_html=True)
        else: st.markdown("<div class='taksi-card'>Ei muita tiedossa olevia yleisötapahtumia tälle illalle.</div>", unsafe_allow_html=True)

    # PIKALINKIT
    st.markdown("<div class='section-header'>📋 OPERATIIVISET PIKALINKIT</div>", unsafe_allow_html=True)
    st.markdown(f"""
    <div class='taksi-card'>
        <div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;font-size:17px;'>
          <div>
            <b style='color:#5bc0de;'>Liikenne</b><br>
            <a href='https://www.vr.fi/radalla/poikkeustilanteet' class='taksi-link' target='_blank' style='font-size:15px;'>VR Poikkeukset &#x2192;</a><br>
            <a href='{HSL_LINKKI}' class='taksi-link' target='_blank' style='font-size:15px;'>HSL Häiriöt &#x2192;</a><br>
            <a href='https://liikennetilanne.fintraffic.fi/?x=385557.5&y=6672322.0&z=10' class='taksi-link' target='_blank' style='font-size:15px;'>Fintraffic Uusimaa &#x2192;</a>
          </div>
          <div>
            <b style='color:#5bc0de;'>Sää</b><br>
            <a href='https://www.ilmatieteenlaitos.fi/sade-ja-pilvialueet?area=etela-suomi' class='taksi-link' target='_blank' style='font-size:15px;'>Sadetutka Etelä-Suomi &#x2192;</a><br>
            <a href='https://www.ilmatieteenlaitos.fi/paikallissaa/helsinki' class='taksi-link' target='_blank' style='font-size:15px;'>Helsinki Paikallissää &#x2192;</a>
          </div>
          <div>
            <b style='color:#5bc0de;'>Meriliikenne</b><br>
            <a href='https://averio.fi/laivat' class='taksi-link' target='_blank' style='font-size:15px;'>Averio Laivat &#x2192;</a><br>
            <a href='https://www.portofhelsinki.fi/matkustajille/matkustajatietoa/lahtevat-ja-saapuvat-matkustajalaivat/#tabs-2' class='taksi-link' target='_blank' style='font-size:15px;'>Port of Helsinki &#x2192;</a>
          </div>
        </div>
        <hr style='border-color:#333;margin:16px 0;'>
        <div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;font-size:17px;'>
          <div>
            <b style='color:#5bc0de;'>Lentoliikenne</b><br>
            <a href='https://www.finavia.fi/fi/lentoasemat/helsinki-vantaa/lennot?tab=arr' class='taksi-link' target='_blank' style='font-size:15px;'>Finavia Saapuvat &#x2192;</a>
          </div>
          <div>
            <b style='color:#5bc0de;'>Business & Tapahtumat</b><br>
            <a href='https://tapahtumat.klubi.fi/tapahtumat/' class='taksi-link' target='_blank' style='font-size:15px;'>Suomalainen Klubi &#x2192;</a><br>
            <a href='https://klubben.fi/start/program/' class='taksi-link' target='_blank' style='font-size:15px;'>Svenska Klubben &#x2192;</a><br>
            <a href='https://messukeskus.com/kavijalle/tapahtumat/tapahtumakalenteri/' class='taksi-link' target='_blank' style='font-size:15px;'>Messukeskus &#x2192;</a><br>
            <a href='https://stadissa.fi/' class='taksi-link' target='_blank' style='font-size:15px;'>Stadissa.fi &#x2192;</a>
          </div>
          <div>
            <b style='color:#5bc0de;'>VR Korvaukset</b><br>
            <a href='https://www.vr.fi/asiakaspalvelu/korvaukset-ja-hyvitykset' class='taksi-link' target='_blank' style='font-size:15px;'>VR Myöhästymiskorvaus &#x2192;</a><br>
            <span style='color:#aaa;font-size:14px;'>Oikeutus: &gt;60 min myöhässä + taksilupa konduktööriltä</span>
          </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(
        "<div style='color:#555;font-size:14px;text-align:center;margin-top:20px;'>"
        "TH Taktinen Tutka – Päivittyy 5 min välein (Natiivi) – Digitraffic · Port of Helsinki · Averio · Finavia API"
        "</div>",
        unsafe_allow_html=True,
    )

# Kutsutaan dashboard-funktiota, jos käyttäjä on kirjautunut sisään
if st.session_state.authenticated:
    render_dashboard()
