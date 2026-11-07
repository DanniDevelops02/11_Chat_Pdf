import hashlib
import io
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from html import escape

import streamlit as st

try:
    from pypdf import PdfReader
except ImportError:  # se avisa más abajo
    PdfReader = None

try:
    import openai
    from openai import OpenAI
except ImportError:  # sin la librería solo funciona el modo sin clave
    openai = None
    OpenAI = None

st.set_page_config(
    page_title="Chat con tu PDF · Daniel Flórez",
    page_icon="📖",
    layout="centered",
    initial_sidebar_state="expanded",
)

# =====================================================================
#  CONFIGURACIÓN
# =====================================================================
SIN_CLAVE = "Sin clave · búsqueda en el documento"

# Todos estos servicios hablan el mismo "idioma" que OpenAI, así que usamos una sola librería.
# Los nombres de modelo cambian con frecuencia: si uno falla, usa «Cargar modelos».
PROVEEDORES = {
    SIN_CLAVE: {},
    "Google Gemini · plan gratuito": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "modelo": "gemini-flash-latest",
        "secreto": "GEMINI_API_KEY",
        "clave_url": "https://aistudio.google.com/apikey",
        "nota": "Gratis sin tarjeta, con límites por minuto y por día. En el plan gratuito, Google "
        "puede usar lo que envíes para mejorar sus productos: no subas documentos confidenciales.",
    },
    "Groq · plan gratuito": {
        "base_url": "https://api.groq.com/openai/v1",
        "modelo": "openai/gpt-oss-20b",
        "secreto": "GROQ_API_KEY",
        "clave_url": "https://console.groq.com/keys",
        "nota": "Gratis sin tarjeta y muy rápido, con límites de uso. Revisa su política de datos "
        "antes de enviar documentos privados.",
    },
    "OpenRouter · modelos gratuitos": {
        "base_url": "https://openrouter.ai/api/v1",
        "modelo": "openrouter/free",
        "secreto": "OPENROUTER_API_KEY",
        "clave_url": "https://openrouter.ai/keys",
        "nota": "Los modelos con sufijo «:free» no cobran, pero tienen un tope diario de solicitudes "
        "(50 al día en cuentas nuevas) y cambian con frecuencia.",
    },
    "OpenAI · de pago": {
        "base_url": None,
        "modelo": "gpt-4o-mini",
        "secreto": "OPENAI_API_KEY",
        "clave_url": "https://platform.openai.com/api-keys",
        "nota": "Requiere saldo en tu cuenta de OpenAI.",
    },
    "Otro servicio compatible con OpenAI": {
        "base_url": "",
        "modelo": "",
        "secreto": "LLM_API_KEY",
        "clave_url": None,
        "nota": "Sirve para cualquier servicio con API compatible con OpenAI (incluido Ollama en tu "
        "computador: http://localhost:11434/v1, que solo funciona si ejecutas la app en local).",
    },
}

PROMPT_SISTEMA = (
    "Eres un asistente que responde preguntas sobre un documento PDF. Usa únicamente la "
    "información del contexto que se te entrega. Si la respuesta no aparece en el contexto, "
    "dilo con claridad y no inventes nada. Responde en el mismo idioma de la pregunta, de forma "
    "clara y breve, y menciona las páginas relevantes entre paréntesis, por ejemplo (p. 3)."
)

EXCLUIR_MODELOS = (
    "embed", "whisper", "tts", "imagen", "image", "audio", "guard", "moderation",
    "veo", "lyria", "dall-e", "transcribe", "robotics", "computer-use",
)

# Fondo de página tipo cuaderno: (imagen del patrón, tamaño del patrón)
PATRONES = {
    "Puntos": (
        "radial-gradient(circle, rgba(63,113,166,.30) 1.5px, transparent 1.7px)",
        "26px 26px",
    ),
    "Rayas": (
        "linear-gradient(rgba(63,113,166,.20) 1px, transparent 1px)",
        "100% 34px",
    ),
    "Cuadrícula": (
        "linear-gradient(rgba(63,113,166,.16) 1px, transparent 1px), "
        "linear-gradient(90deg, rgba(63,113,166,.16) 1px, transparent 1px)",
        "28px 28px, 28px 28px",
    ),
    "Liso": (None, None),
}

# =====================================================================
#  ESTILO (paleta fría basada en #3f71a6)
# =====================================================================
PRIMARIO = "#3f71a6"
OSCURO = "#1b2f45"
CLARO = "#eaf2f9"
SUAVE = "#a9c7e3"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Caveat:wght@500;600&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600&family=Playfair+Display:wght@500;600;700&display=swap');

html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif; font-size: 1.06rem; }
.stApp { background-color: #f6fafd; __PATRON__ }
header[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 860px; padding-top: 3rem; padding-bottom: 4rem; }

/* Hero */
.hero { text-align: center; padding: 1rem 0 .5rem 0; }
.hero .etiqueta {
    font-family: 'Caveat', cursive; font-size: 1.8rem; font-weight: 600;
    color: __PRIMARIO__; line-height: 1;
}
.hero h1 {
    font-family: 'Playfair Display', serif; font-size: 3.1rem; color: __OSCURO__;
    margin: .3rem 0 .6rem 0; line-height: 1.12;
}
.hero h1 .marca {
    background: linear-gradient(transparent 62%, rgba(169, 199, 227, .75) 62%);
    padding: 0 .12em;
}
.hero p { color: #4d6479; font-size: 1.2rem; max-width: 620px; margin: 0 auto; }
.linea { width: 70px; height: 4px; border-radius: 4px; background: __PRIMARIO__; margin: 1.4rem auto; }
h2, h3 { font-family: 'Playfair Display', serif !important; color: __OSCURO__ !important; }

/* Tarjetas con "cinta washi" (contenedores con key="tarjeta_...") */
[class*="st-key-tarjeta"] {
    position: relative; box-sizing: border-box;
    background: #ffffff !important;
    border: 1px solid __SUAVE__99 !important;
    border-radius: 18px !important;
    box-shadow: 0 8px 24px rgba(63, 113, 166, .10);
    padding: 1.4rem 1.5rem 1.3rem 1.5rem !important;
}
[class*="st-key-tarjeta"]::before {
    content: ""; position: absolute; top: -10px; left: 28px; width: 80px; height: 20px;
    background: rgba(169, 199, 227, .75); border-radius: 2px;
    transform: rotate(-1.5deg); box-shadow: 0 1px 2px rgba(27, 47, 69, .10); z-index: 2;
}
[data-testid="stHeaderActionElements"] { display: none !important; }

/* Datos del documento */
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: .6rem 0 .2rem 0; }
.chip {
    background: #f6fafd; border: 1px dashed __SUAVE__; border-radius: 999px;
    padding: 5px 14px; font-size: .88rem; font-weight: 500; color: __OSCURO__;
}

/* Conversación */
[class*="st-key-burbuja_usuario"] {
    background: __CLARO__; border: 1px solid __SUAVE__66; border-radius: 18px 18px 4px 18px;
    padding: .8rem 1.1rem; margin: .7rem 0 .7rem 14%;
}
[class*="st-key-burbuja_asistente"] {
    background: #ffffff; border: 1px dashed __SUAVE__; border-radius: 18px 18px 18px 4px;
    padding: .9rem 1.1rem; margin: .7rem 6% .7rem 0;
}
.rol { font-family: 'Caveat', cursive; font-size: 1.25rem; color: __PRIMARIO__; line-height: 1; margin-bottom: .2rem; }
.pasaje {
    border-left: 3px solid __PRIMARIO__; background: #f6fafd; border-radius: 0 10px 10px 0;
    padding: .55rem .85rem; margin: .5rem 0; font-size: .93rem; line-height: 1.55; color: #324b63;
}
.pasaje .pag { font-family: 'IBM Plex Mono', monospace; font-size: .78rem; color: #6b8399; display: block; margin-bottom: 2px; }
.pasaje mark { background: rgba(255, 210, 63, .45); border-radius: 3px; padding: 0 2px; }

/* Botones e inputs */
.stButton > button, .stDownloadButton > button {
    background: __PRIMARIO__; color: white; border: 1.5px solid __PRIMARIO__;
    border-radius: 999px; padding: .6rem 1.4rem; font-weight: 600; transition: all .2s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    background: __OSCURO__; border-color: __OSCURO__; color: white; transform: translateY(-2px);
}
.stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
    border-radius: 12px; border: 1px solid __SUAVE__;
}
[data-testid="stFileUploaderDropzone"] { background: __CLARO__; border: 2px dashed __SUAVE__; border-radius: 16px; }
[data-testid="stAlert"] { border-radius: 14px; }

/* Sidebar */
[data-testid="stSidebar"] { background: __OSCURO__; }
[data-testid="stSidebar"] * { color: #e6f0f9 !important; }

#MainMenu, footer { visibility: hidden; }
</style>
"""


def construir_css(patron: str) -> str:
    imagen, tamano = PATRONES[patron]
    base = "linear-gradient(180deg, #f6fafd 0%, #eaf2f9 100%)"
    if imagen:
        fondo = f"background-image: {imagen}, {base}; background-size: {tamano}, 100% 100%;"
    else:
        fondo = f"background-image: {base};"
    css = CSS.replace("__PATRON__", fondo)
    for token, valor in {
        "__PRIMARIO__": PRIMARIO,
        "__OSCURO__": OSCURO,
        "__CLARO__": CLARO,
        "__SUAVE__": SUAVE,
    }.items():
        css = css.replace(token, valor)
    return css


# =====================================================================
#  LÓGICA: TEXTO Y BÚSQUEDA (sin claves ni servicios externos)
# =====================================================================
def quitar_tildes(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", texto)
    sin_marcas = re.sub(r"(?<!n)[\u0300-\u036f]", "", nfd)
    return unicodedata.normalize("NFC", sin_marcas)


_PALABRAS_VACIAS = """
a al algo ante antes aqui asi aun aunque bajo cada como con contra cual cuales cuando cuanto de del
desde donde dos durante e el ella ellas ellos en entre era es esa esas ese eso esos esta estan estar
este esto estos fue ha han hay he hasta la las le les lo los mas me mi mis muy ni no nos o otra otro
para pero poco por porque que quien se sea segun ser si sin sobre son su sus tambien tan te tiene
tienen todo todos tu tus un una uno unos y ya yo cual cuales cuantos como donde cuando quien
the and of to in is it are was for on that this with as by at be from or an have has had not but
what which who how when where why does do did can could should would about into
"""
PALABRAS_VACIAS = {quitar_tildes(p) for p in _PALABRAS_VACIAS.split()}


def raiz(palabra: str) -> str:
    """Raíz sencilla para que coincidan plurales y género: grande/grandes, mercado/mercados."""
    if len(palabra) > 5 and palabra.endswith("es"):
        palabra = palabra[:-2]  # ciudades -> ciudad, flores -> flor
    elif len(palabra) > 4 and palabra.endswith("s"):
        palabra = palabra[:-1]  # mercados -> mercado
    if len(palabra) > 4 and palabra[-1] in "aeo":
        palabra = palabra[:-1]  # grande -> grand, mercado -> mercad
    return palabra


def tokenizar(texto: str) -> list:
    palabras = re.findall(r"[^\W_]+", quitar_tildes(texto.lower()))
    return [raiz(p) for p in palabras if len(p) >= 2 and p not in PALABRAS_VACIAS]


class BM25:
    """Ranking clásico de relevancia por palabras (el que usan muchos buscadores)."""

    def __init__(self, documentos, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.n = len(documentos)
        self.longitudes = [len(d) for d in documentos]
        self.promedio = (sum(self.longitudes) / self.n) if self.n else 1.0
        self.indice = defaultdict(list)  # palabra -> [(documento, frecuencia)]
        for i, doc in enumerate(documentos):
            for palabra, frecuencia in Counter(doc).items():
                self.indice[palabra].append((i, frecuencia))
        self.idf = {
            p: math.log((self.n - len(lista) + 0.5) / (len(lista) + 0.5) + 1)
            for p, lista in self.indice.items()
        }

    def puntuar(self, consulta: list) -> list:
        puntajes = [0.0] * self.n
        for palabra in set(consulta):
            for i, frecuencia in self.indice.get(palabra, ()):
                norma = 1 - self.b + self.b * self.longitudes[i] / (self.promedio or 1.0)
                puntajes[i] += self.idf[palabra] * frecuencia * (self.k1 + 1) / (frecuencia + self.k1 * norma)
        return puntajes


def dividir_pagina(texto: str, pagina: int, tam: int = 900) -> list:
    """Parte una página en fragmentos de unos 900 caracteres, cortando por frases."""
    texto = re.sub(r"-\n(?=\w)", "", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    frases = []
    for parrafo in re.split(r"\n\s*\n", texto):
        parrafo = re.sub(r"\s*\n\s*", " ", parrafo).strip()
        if parrafo:
            frases.extend(re.split(r"(?<=[.!?;:])\s+", parrafo))

    fragmentos, actual, ultima = [], "", ""
    for frase in frases:
        frase = frase.strip()
        if not frase:
            continue
        while len(frase) > tam:
            if actual:
                fragmentos.append(actual)
                actual = ""
            fragmentos.append(frase[:tam])
            frase = frase[tam:]
        if actual and len(actual) + 1 + len(frase) > tam:
            fragmentos.append(actual)
            actual = ultima if len(ultima) < 200 else ""  # solapa una frase para no perder contexto
        actual = (actual + " " + frase).strip()
        ultima = frase
    if actual.strip():
        fragmentos.append(actual)
    return [(pagina, f) for f in fragmentos if len(f) > 20]


@st.cache_resource(show_spinner=False, max_entries=3)
def procesar_pdf(datos: bytes) -> dict:
    """Extrae el texto, lo divide en fragmentos y prepara el buscador."""
    lector = PdfReader(io.BytesIO(datos))
    if lector.is_encrypted:
        try:
            lector.decrypt("")
        except Exception:
            raise ValueError("El PDF está protegido con contraseña.")

    fragmentos, palabras, con_texto = [], 0, 0
    for numero, pagina in enumerate(lector.pages, 1):
        try:
            texto = pagina.extract_text() or ""
        except Exception:
            texto = ""
        if texto.strip():
            con_texto += 1
            palabras += len(texto.split())
        fragmentos.extend(dividir_pagina(texto, numero))

    return {
        "paginas": len(lector.pages),
        "con_texto": con_texto,
        "palabras": palabras,
        "fragmentos": fragmentos,
        "bm25": BM25([tokenizar(t) for _, t in fragmentos]) if fragmentos else None,
    }


def buscar(documento: dict, pregunta: str, k: int):
    """Devuelve (pasajes relevantes, términos de la pregunta)."""
    terminos = tokenizar(pregunta)
    if not terminos or documento["bm25"] is None:
        return [], set()
    puntajes = documento["bm25"].puntuar(terminos)
    orden = sorted(range(len(puntajes)), key=lambda i: puntajes[i], reverse=True)[:k]
    pasajes = [
        (documento["fragmentos"][i][0], documento["fragmentos"][i][1], puntajes[i])
        for i in orden
        if puntajes[i] > 0
    ]
    return pasajes, set(terminos)


def resaltar(texto: str, terminos: set) -> str:
    """Devuelve HTML seguro con las palabras de la pregunta marcadas."""
    piezas = re.split(r"([^\W_]+)", texto)
    salida = []
    for i, pieza in enumerate(piezas):
        if i % 2 == 1 and raiz(quitar_tildes(pieza.lower())) in terminos:
            salida.append(f"<mark>{escape(pieza)}</mark>")
        else:
            salida.append(escape(pieza))
    return "".join(salida).replace("\n", " ")


def pasajes_html(pasajes: list, terminos: set) -> str:
    return "".join(
        f'<div class="pasaje"><span class="pag">página {pagina}</span>{resaltar(texto, terminos)}</div>'
        for pagina, texto, _ in pasajes
    )


# =====================================================================
#  LÓGICA: MODELOS DE LENGUAJE (opcional, con clave)
# =====================================================================
def crear_cliente(config: dict, timeout: int = 60):
    return OpenAI(
        api_key=config["clave"],
        base_url=config["base_url"] or None,
        timeout=timeout,
        max_retries=1,
    )


def listar_modelos(config: dict) -> list:
    cliente = crear_cliente(config, timeout=30)
    ids = []
    for modelo in cliente.models.list():
        nombre = modelo.id.removeprefix("models/")
        if any(x in nombre.lower() for x in EXCLUIR_MODELOS):
            continue
        ids.append(nombre)
    if config["etiqueta"].startswith("OpenRouter"):
        ids = [i for i in ids if i.endswith(":free") or i == "openrouter/free"]
    return sorted(set(ids))


def preguntar_llm(config: dict, pregunta: str, pasajes: list, historial: list) -> str:
    cliente = crear_cliente(config)
    contexto = "\n\n".join(f"[Página {p}] {t}" for p, t, _ in pasajes)
    mensajes = [{"role": "system", "content": PROMPT_SISTEMA}]
    for m in historial[-6:]:
        if m["modo"] == "llm" or m["rol"] == "usuario":
            mensajes.append(
                {"role": "user" if m["rol"] == "usuario" else "assistant", "content": m["contenido"]}
            )
    mensajes.append(
        {"role": "user", "content": f"Contexto del documento:\n{contexto}\n\nPregunta: {pregunta}"}
    )
    try:
        respuesta = cliente.chat.completions.create(
            model=config["modelo"], messages=mensajes, temperature=0.2
        )
    except Exception as error:
        if "temperature" in str(error).lower():  # algunos modelos no aceptan este parámetro
            respuesta = cliente.chat.completions.create(model=config["modelo"], messages=mensajes)
        else:
            raise
    texto = (respuesta.choices[0].message.content or "").strip()
    if not texto:
        raise ValueError("El modelo devolvió una respuesta vacía.")
    return texto


def explicar_error(error: Exception) -> str:
    if openai is not None:
        if isinstance(error, openai.AuthenticationError):
            return "La clave no es válida o no tiene permiso para este servicio."
        if isinstance(error, openai.RateLimitError):
            return (
                "Se alcanzó el límite del plan gratuito o el modelo está saturado. "
                "Espera un minuto, prueba otro modelo o usa el modo sin clave."
            )
        if isinstance(error, openai.NotFoundError):
            return "Ese modelo no existe en este servicio. Pulsa «Cargar modelos» y elige uno de la lista."
        if isinstance(error, openai.APIConnectionError):
            return "No se pudo conectar con el servicio. Revisa tu conexión a internet."
    return f"El servicio devolvió un error: {str(error)[:180]}"


def clave_guardada(nombre: str):
    """Busca la clave en los secretos de la app o en variables de entorno (nunca la escribe)."""
    try:
        valor = st.secrets.get(nombre)
        if valor:
            return str(valor)
    except Exception:
        pass
    return os.environ.get(nombre) or None


# =====================================================================
#  CALLBACKS
# =====================================================================
def borrar_conversacion():
    st.session_state["mensajes"] = []


# =====================================================================
#  PÁGINA
# =====================================================================
st.session_state.setdefault("mensajes", [])

with st.sidebar:
    st.subheader("Cómo usarlo")
    st.markdown(
        "1. Sube un PDF con texto.\n"
        "2. Elige cómo quieres las respuestas.\n"
        "3. Pregunta lo que necesites sobre el documento."
    )
    st.subheader("Privacidad")
    st.markdown(
        "El PDF se procesa en el servidor de esta app. Si eliges un motor de IA, solo los "
        "pasajes relevantes y tu pregunta se envían a ese servicio."
    )
    st.subheader("Estilo de la página")
    patron = st.radio(
        "Fondo de cuaderno", list(PATRONES), horizontal=True, label_visibility="collapsed"
    )

st.markdown(construir_css(patron), unsafe_allow_html=True)

st.markdown(
    """
    <div class="hero">
        <div class="etiqueta">cuaderno de lectura ✎</div>
        <h1>Chatea con tu <span class="marca">PDF</span></h1>
        <p>Sube un documento y pregúntale lo que necesites. Funciona incluso sin clave de IA.</p>
        <div class="linea"></div>
    </div>
    """,
    unsafe_allow_html=True,
)

if PdfReader is None:
    st.error("Falta la librería `pypdf`. Agrégala a `requirements.txt` y reinicia la app.")
    st.stop()

# ---- 1. Documento ----
with st.container(key="tarjeta_documento"):
    st.subheader("1 · Tu documento")
    pdf = st.file_uploader("Carga el archivo PDF", type="pdf", label_visibility="collapsed")

documento = None
if pdf is not None:
    datos = pdf.getvalue()
    huella = hashlib.md5(datos).hexdigest()
    if st.session_state.get("huella_pdf") != huella:
        st.session_state["huella_pdf"] = huella
        st.session_state["mensajes"] = []
    try:
        with st.spinner("Leyendo el documento..."):
            documento = procesar_pdf(datos)
    except Exception as error:
        st.error(f"No se pudo leer el PDF. ({error})")
        st.stop()

    if not documento["fragmentos"]:
        st.warning(
            "No se encontró texto en este PDF. Si es un documento escaneado, primero hay que "
            "pasarlo por un OCR (por ejemplo, con la app de reconocimiento de texto)."
        )
        documento = None
    else:
        st.markdown(
            '<div class="chips">'
            f'<span class="chip">📄 {documento["paginas"]} páginas</span>'
            f'<span class="chip">🧩 {len(documento["fragmentos"])} fragmentos</span>'
            f'<span class="chip">✍️ {documento["palabras"]:,} palabras</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        if documento["con_texto"] < documento["paginas"]:
            st.caption(
                f"{documento['paginas'] - documento['con_texto']} página(s) no tienen texto "
                "(imágenes o escaneos) y no se pueden consultar."
            )

st.write("")

# ---- 2. Motor de respuestas ----
with st.container(key="tarjeta_motor"):
    st.subheader("2 · Cómo responder")
    etiqueta = st.selectbox("Motor de respuestas", list(PROVEEDORES), label_visibility="collapsed")
    preset = PROVEEDORES[etiqueta]
    config = {"modo": "local"}

    if etiqueta == SIN_CLAVE:
        st.caption(
            "Sin IA: la app busca en el documento los pasajes que mejor responden a tu pregunta "
            "y te los muestra con las palabras clave resaltadas. No redacta respuestas, pero no "
            "necesita clave, es gratis y no envía tu documento a ningún servicio."
        )
    else:
        st.caption(preset["nota"])
        if OpenAI is None:
            st.warning("Falta la librería `openai` en `requirements.txt` para usar este motor.")
        else:
            guardada = clave_guardada(preset["secreto"])
            if guardada:
                clave = guardada
                st.success("Se usa la clave guardada en la configuración de la app.")
            else:
                clave = st.text_input(
                    "Tu clave de API",
                    type="password",
                    key=f"clave_{etiqueta}",
                    placeholder="Pega tu clave aquí",
                )
                if preset["clave_url"]:
                    st.caption(f"¿No tienes una? Se crea gratis en {preset['clave_url']}")

            base_url = preset["base_url"]
            if base_url == "":
                base_url = st.text_input("Dirección del servicio (base URL)", placeholder="https://.../v1")

            modelo_defecto = preset["modelo"]
            lista_clave = f"modelos_{etiqueta}"
            if st.session_state.get(lista_clave):
                lista = st.session_state[lista_clave]
                indice = lista.index(modelo_defecto) if modelo_defecto in lista else 0
                modelo = st.selectbox("Modelo", lista, index=indice)
            else:
                modelo = st.text_input("Modelo", value=modelo_defecto, key=f"modelo_{etiqueta}")

            config_prueba = {
                "etiqueta": etiqueta, "base_url": base_url, "clave": clave, "modelo": modelo,
            }
            if clave and st.button("Cargar modelos disponibles"):
                try:
                    with st.spinner("Consultando el servicio..."):
                        st.session_state[lista_clave] = listar_modelos(config_prueba)
                    if not st.session_state[lista_clave]:
                        st.info("El servicio no devolvió modelos de chat.")
                    st.rerun()
                except Exception as error:
                    st.error(explicar_error(error))

            if clave and modelo:
                config = {"modo": "llm", **config_prueba}
            elif not clave:
                st.info("Sin clave se usará la búsqueda en el documento.")

    with st.expander("Opciones de búsqueda"):
        k = st.slider("Pasajes a consultar por pregunta", 2, 8, 4)

st.write("")

# ---- 3. Conversación ----
if documento is None:
    st.info("Carga un PDF con texto para empezar a preguntar.")
    st.stop()

with st.container(key="tarjeta_chat"):
    st.subheader("3 · Pregunta sobre el documento")
    zona_mensajes = st.container()
    pregunta = st.chat_input("Escribe tu pregunta aquí...")

    if pregunta:
        historial = list(st.session_state["mensajes"])
        pasajes, terminos = buscar(documento, pregunta, k)
        st.session_state["mensajes"].append({"rol": "usuario", "contenido": pregunta, "modo": "usuario"})

        if config["modo"] == "llm" and pasajes:
            try:
                with st.spinner("Pensando..."):
                    texto = preguntar_llm(config, pregunta, pasajes, historial)
                respuesta = {"modo": "llm", "contenido": texto}
            except Exception as error:
                respuesta = {
                    "modo": "error",
                    "contenido": f"No pude consultar el modelo. {explicar_error(error)} "
                    "Mientras tanto, estos son los pasajes más relevantes:",
                }
        elif pasajes:
            respuesta = {"modo": "local", "contenido": "Estos son los pasajes del documento más relacionados con tu pregunta:"}
        else:
            respuesta = {
                "modo": "local",
                "contenido": "No encontré pasajes relacionados. Prueba con otras palabras, "
                "más específicas o que aparezcan en el documento.",
            }
        st.session_state["mensajes"].append(
            {"rol": "asistente", "pasajes": pasajes, "terminos": terminos, **respuesta}
        )

    with zona_mensajes:
        if not st.session_state["mensajes"]:
            st.caption("Aún no hay preguntas. Escribe la primera abajo.")
        for i, mensaje in enumerate(st.session_state["mensajes"]):
            if mensaje["rol"] == "usuario":
                with st.container(key=f"burbuja_usuario_{i}"):
                    st.markdown('<div class="rol">tú</div>', unsafe_allow_html=True)
                    st.markdown(mensaje["contenido"])
            else:
                with st.container(key=f"burbuja_asistente_{i}"):
                    st.markdown('<div class="rol">asistente</div>', unsafe_allow_html=True)
                    if mensaje["modo"] == "llm":
                        st.markdown(mensaje["contenido"])
                        if mensaje["pasajes"]:
                            with st.expander("Ver los pasajes consultados"):
                                st.markdown(
                                    pasajes_html(mensaje["pasajes"], mensaje["terminos"]),
                                    unsafe_allow_html=True,
                                )
                    else:
                        st.markdown(escape(mensaje["contenido"]))
                        if mensaje["pasajes"]:
                            st.markdown(
                                pasajes_html(mensaje["pasajes"], mensaje["terminos"]),
                                unsafe_allow_html=True,
                            )

    if st.session_state["mensajes"]:
        st.button("Borrar la conversación", on_click=borrar_conversacion)

st.write("")
st.caption("Búsqueda con BM25. Respuestas redactadas con el servicio de IA que elijas (opcional).")
