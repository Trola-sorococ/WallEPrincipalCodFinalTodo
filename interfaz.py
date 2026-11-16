import queue
import re
import sys
import threading

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("ERROR: Instala 'pyserial' ejecutando: pip install pyserial")
    sys.exit()

import tkinter as tk
from tkinter import ttk, messagebox

# --- CONSTANTES ---
BAUDIOS = 9600
DIST_FRENADO_CM = 20          # Distancia de frenado de emergencia
DIST_AVISO_CM = 50            # Por debajo de esta distancia el sensor se muestra en ámbar
INTERVALO_COLA_MS = 50        # Cada cuánto la interfaz revisa los datos del sensor
RE_DIST = re.compile(rb"DIST:(\d+)")

# --- ESTILO ---
FUENTE = "Segoe UI"
TEMA_INICIAL = "Carbón y Ámbar"   # Cambia este nombre para arrancar con otro tema
HUECO = 6                         # Separación (px) entre botones de la cruceta
RUTINA_CABEZA_S = 10              # Duración de la rutina de la cabeza: 2 tramos de 5 s, igual que el .ino

# Cada tema define los mismos colores; el resto de la interfaz solo usa estos nombres.
TEMAS = {
    "Carbón y Ámbar": dict(
        oscuro=True,
        fondo="#12151A", superficie="#1A1E25", superficie2="#232834", borde="#2D3441",
        texto="#E9EBEF", apagado="#8D96A5",
        acento="#F5A524", exito="#2FD08A", peligro="#EF4F4F", aviso="#F5C542"),
    "Azul Medianoche": dict(
        oscuro=True,
        fondo="#0B1220", superficie="#111A2B", superficie2="#18243A", borde="#25344F",
        texto="#E6ECF5", apagado="#8696B0",
        acento="#3B82F6", exito="#22C55E", peligro="#EF4444", aviso="#F59E0B"),
    "Grafito y Cian": dict(
        oscuro=True,
        fondo="#0E1317", superficie="#151C22", superficie2="#1D262E", borde="#2A3540",
        texto="#E7EEF3", apagado="#8A9AA8",
        acento="#22D3EE", exito="#4ADE80", peligro="#F87171", aviso="#FBBF24"),
    "Claro Profesional": dict(
        oscuro=False,
        fondo="#EEF1F6", superficie="#FFFFFF", superficie2="#F3F5F9", borde="#D3D9E3",
        texto="#1B2430", apagado="#667386",
        acento="#2563EB", exito="#16A34A", peligro="#DC2626", aviso="#D97706"),
}

# Grupos de servos: (título, detalle, ¿botones lado a lado?,
#                    [(texto, comando al presionar, comando al soltar)])
GRUPOS_SERVOS = [
    ("BRAZO IZQUIERDO", "pin 8", False, [("▲   SUBIR", '4', '6'), ("▼   BAJAR", '5', '6')]),
    ("AMBOS BRAZOS", "pines 8 y 10", False, [("▲   SUBIR", 'U', 'N'), ("▼   BAJAR", 'D', 'N')]),
    ("CABEZA", "pin 9", True, [("◀   IZQ", '1', '3'), ("DER   ▶", '2', '3')]),
    ("BRAZO DERECHO", "pin 10", False, [("▲   SUBIR", '7', '9'), ("▼   BAJAR", '8', '9')]),
]


def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def mezclar(color_a, color_b, cantidad):
    """Mezcla dos colores hex. cantidad=0 devuelve color_a y cantidad=1 devuelve color_b."""
    a, b = _rgb(color_a), _rgb(color_b)
    return "#%02X%02X%02X" % tuple(round(a[i] + (b[i] - a[i]) * cantidad) for i in range(3))


def texto_sobre(color):
    """Texto oscuro o claro según el brillo del color de fondo."""
    r, g, b = _rgb(color)
    return "#14161A" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#FFFFFF"


class Boton(tk.Frame):
    """Botón plano de tamaño fijo con estados: normal, encima, presionado y deshabilitado.

    - al_presionar / al_soltar: para botones de "mantener presionado" (al_soltar siempre se llama).
    - al_click: se ejecuta al soltar con el mouse todavía encima del botón.
    - estilo: "secundario" (neutro), "primario" (acento), "exito" o "peligro".
    """

    def __init__(self, parent, app, texto, estilo="secundario", ancho=160, alto=56,
                 fuente=None, icono=None, tam_icono=18, al_presionar=None, al_soltar=None,
                 al_click=None, control=False):
        super().__init__(parent, width=app.px(ancho), height=app.px(alto), highlightthickness=1)
        self.pack_propagate(False)
        self.tema = app.tema
        self.estilo = estilo
        self.habilitado = True
        self.encima = False
        self.presionado = False
        self.al_presionar = al_presionar
        self.al_soltar = al_soltar
        self.al_click = al_click

        # El contenido (icono opcional + texto) queda centrado en el botón
        self.contenido = tk.Frame(self)
        self.contenido.pack(expand=True)
        self.icono = None
        if icono:
            self.icono = tk.Label(self.contenido, text=icono, font=(FUENTE, tam_icono, "bold"))
            self.icono.pack()
        self.etiqueta = tk.Label(self.contenido, text=texto, font=fuente or app.fuente_boton,
                                 justify="center")
        self.etiqueta.pack()

        self.piezas = [self, self.contenido, self.etiqueta] + ([self.icono] if self.icono else [])
        for pieza in self.piezas:
            pieza.bind("<Enter>", self._actualizar_encima)
            pieza.bind("<Leave>", self._actualizar_encima)
            pieza.bind("<ButtonPress-1>", self._presionar)
            pieza.bind("<ButtonRelease-1>", self._soltar)
        self._pintar()

        if control:                     # Los botones de control se deshabilitan sin conexión
            app.botones_control.append(self)

    def _pintar(self):
        t = self.tema
        if not self.habilitado:
            bg = t["superficie2"]
            fg = mezclar(t["apagado"], bg, 0.35)
            borde = t["borde"]
            cursor = "arrow"
        else:
            cursor = "hand2"
            if self.estilo == "secundario":
                bg, fg, borde = t["superficie2"], t["texto"], t["borde"]
                if self.presionado:
                    bg, fg, borde = t["acento"], texto_sobre(t["acento"]), t["acento"]
                elif self.encima:
                    bg, borde = mezclar(bg, t["texto"], 0.08), t["acento"]
            else:
                base = {"primario": t["acento"], "exito": t["exito"], "peligro": t["peligro"]}[self.estilo]
                bg = borde = base
                fg = texto_sobre(base)
                if self.presionado:
                    bg = borde = mezclar(base, "#000000", 0.20)
                elif self.encima:
                    bg = borde = mezclar(base, "#FFFFFF" if t["oscuro"] else "#000000", 0.14)
        self.configure(bg=bg, highlightbackground=borde, highlightcolor=borde)
        for pieza in self.piezas:
            pieza.configure(bg=bg, cursor=cursor)
        for texto in (self.etiqueta, self.icono):
            if texto is not None:
                texto.configure(fg=fg)

    def _puntero_encima(self):
        """Comprueba con la posición real del mouse (más fiable que los eventos Enter/Leave)."""
        x, y = self.winfo_pointerxy()
        izquierda, arriba = self.winfo_rootx(), self.winfo_rooty()
        return (izquierda <= x < izquierda + self.winfo_width()
                and arriba <= y < arriba + self.winfo_height())

    def _actualizar_encima(self, _=None):
        encima = self._puntero_encima()
        if encima != self.encima:
            self.encima = encima
            self._pintar()

    def _presionar(self, _):
        if not self.habilitado:
            return
        self.presionado = True
        self._pintar()
        if self.al_presionar:
            self.al_presionar()

    def _soltar(self, _):
        if not self.presionado:
            return
        self.presionado = False
        dentro = self._puntero_encima()
        self.encima = dentro
        self._pintar()
        if self.al_soltar:
            self.al_soltar()
        if self.al_click and dentro:
            self.al_click()

    def set_texto(self, texto):
        self.etiqueta.configure(text=texto)

    def set_estilo(self, estilo):
        self.estilo = estilo
        self._pintar()

    def set_habilitado(self, habilitado):
        if self.habilitado != habilitado:
            self.habilitado = habilitado
            if not habilitado:
                self.presionado = False
            self._pintar()


class WallEControlApp:
    TXT_AUTO_OFF = "MODO AUTO   ·   1 TOQUE"
    TXT_AUTO_ON = "AUTO ACTIVO   ·   TOCA PARA DETENER"
    TXT_RUTINA_OFF = f"AUTO   ·   RUTINA {RUTINA_CABEZA_S} s"
    ESTADOS_CONEXION = {
        "desconectado": ("DESCONECTADO", "apagado"),
        "conectando": ("CONECTANDO…", "aviso"),
        "conectado": ("CONECTADO", "exito"),
    }

    def __init__(self, root):
        self.root = root
        self.root.title("COBOT WALL-E · Sistema de control")
        self.escala = max(1.0, root.winfo_fpixels("1i") / 96.0)   # Escala de pantalla (DPI)
        self.root.geometry(f"{self.px(1280)}x{self.px(800)}")
        self.root.minsize(self.px(1100), self.px(720))

        self.nombre_tema = TEMA_INICIAL
        self.tema = TEMAS[TEMA_INICIAL]
        self.fuente_boton = (FUENTE, 11, "bold")
        self.root.configure(bg=self.tema["fondo"])
        try:
            self.root.state('zoomed')
        except tk.TclError:
            pass

        # --- Variables de control ---
        self.arduino = None
        self.hilo_lectura = None
        self.stop_lectura = None            # threading.Event de la conexión actual
        self.conectando = False
        self.cola = queue.Queue()           # Hilos -> interfaz (única vía segura)

        self.modo_actual = "PRINCIPAL"
        self.direccion = None               # None, 'F', 'B', 'L' o 'R'
        self.distancia_sensor = 999
        self.ultima_lectura = None          # Último DIST recibido (None si no hay conexión)
        self.estado_conexion = ("desconectado", "")
        self.auto_con_parada_activo = False
        self.auto_continuo_activo = False
        self.botones_auto_parada = []       # El botón de modo auto aparece en 2 pantallas
        self.botones_control = []           # Botones que requieren conexión
        self.botones_auto_cabeza = []       # El botón AUTO de la cabeza aparece en 2 pantallas
        self.rutina_cabeza_restante = 0     # Segundos que faltan de la rutina (0 = inactiva)
        self._id_rutina = None              # Temporizador de la cuenta regresiva

        self.aplicar_estilos_ttk()
        self.construir_splash()
        self.construir_interfaz()

        self.root.protocol("WM_DELETE_WINDOW", self.al_cerrar)
        self.root.after(INTERVALO_COLA_MS, self.procesar_cola)

        self.paso_animacion = 0
        self.root.after(300, self.ejecutar_animacion_entrada)

    @property
    def motores_en_movimiento(self):
        return self.direccion is not None

    def px(self, n):
        """Convierte píxeles de diseño (96 DPI) a píxeles reales de la pantalla."""
        return int(round(n * self.escala))

    # =========================================================
    # ESTILOS
    # =========================================================
    def aplicar_estilos_ttk(self):
        t = self.tema
        estilo = ttk.Style()
        estilo.theme_use("clam")
        estilo.configure("Cobot.Horizontal.TProgressbar", troughcolor=t["superficie2"],
                         background=t["acento"], bordercolor=t["fondo"],
                         lightcolor=t["acento"], darkcolor=t["acento"], thickness=6)
        estilo.configure("TCombobox", fieldbackground=t["superficie2"], background=t["superficie2"],
                         foreground=t["texto"], arrowcolor=t["texto"], bordercolor=t["borde"],
                         lightcolor=t["superficie2"], darkcolor=t["superficie2"],
                         selectbackground=t["superficie2"], selectforeground=t["texto"], padding=4)
        estilo.map("TCombobox",
                   fieldbackground=[("readonly", t["superficie2"])],
                   foreground=[("readonly", t["texto"])],
                   background=[("active", t["borde"]), ("readonly", t["superficie2"])],
                   selectbackground=[("readonly", t["superficie2"])],
                   selectforeground=[("readonly", t["texto"])],
                   bordercolor=[("focus", t["acento"])])
        # Lista desplegable del combobox
        self.root.option_add("*TCombobox*Listbox.background", t["superficie2"])
        self.root.option_add("*TCombobox*Listbox.foreground", t["texto"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", t["acento"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", texto_sobre(t["acento"]))
        self.root.option_add("*TCombobox*Listbox.font", (FUENTE, 10))

    def cambiar_tema(self, nombre):
        if nombre in TEMAS and nombre != self.nombre_tema:
            # Se reconstruye fuera del evento del combobox para no destruirlo mientras se usa
            self.root.after(20, lambda: self.aplicar_tema(nombre))

    def aplicar_tema(self, nombre):
        puerto = self.combo_ports.get()
        self.nombre_tema = nombre
        self.tema = TEMAS[nombre]
        self.frame_app.destroy()
        self.botones_auto_parada = []
        self.botones_control = []
        self.botones_auto_cabeza = []
        self.aplicar_estilos_ttk()
        self.root.configure(bg=self.tema["fondo"])
        self.construir_interfaz()
        self.frame_app.pack(fill="both", expand=True)
        if puerto in self.combo_ports["values"]:
            self.combo_ports.set(puerto)

    # =========================================================
    # PANTALLA DE ENTRADA
    # =========================================================
    def construir_splash(self):
        t, p = self.tema, self.px
        self.frame_splash = tk.Frame(self.root, bg=t["fondo"])
        self.frame_splash.pack(fill="both", expand=True)

        centro = tk.Frame(self.frame_splash, bg=t["fondo"])
        centro.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(centro, text="COBOT", font=("Segoe UI Black", 64), fg=t["acento"],
                 bg=t["fondo"]).pack()
        tk.Label(centro, text="WALL-E   CONTROL   SYSTEM", font=(FUENTE, 13, "bold"),
                 fg=t["texto"], bg=t["fondo"]).pack(pady=(0, p(34)))

        self.lbl_status = tk.Label(centro, text="INICIANDO SISTEMAS...", font=(FUENTE, 10),
                                   fg=t["apagado"], bg=t["fondo"])
        self.lbl_status.pack(pady=(0, p(10)))

        self.progress = ttk.Progressbar(centro, length=p(460), mode='determinate',
                                        style="Cobot.Horizontal.TProgressbar")
        self.progress.pack()

    def ejecutar_animacion_entrada(self):
        pasos = [
            (20, "Cargando protocolo de transmisión..."),
            (45, "Inicializando módulos Bluetooth..."),
            (70, "Calibrando servos y sensores..."),
            (90, "Configurando controles e interfaz..."),
            (100, "¡SISTEMAS LISTOS!"),
        ]
        if self.paso_animacion < len(pasos):
            porcentaje, texto = pasos[self.paso_animacion]
            self.progress['value'] = porcentaje
            self.lbl_status.config(text=texto)
            self.paso_animacion += 1
            self.root.after(550, self.ejecutar_animacion_entrada)
        else:
            self.root.after(400, self.transicion_a_principal)

    def transicion_a_principal(self):
        self.frame_splash.destroy()
        self.frame_app.pack(fill="both", expand=True)

    # =========================================================
    # ESTRUCTURA DE LA INTERFAZ
    # =========================================================
    def construir_interfaz(self):
        t, p = self.tema, self.px
        self.frame_app = tk.Frame(self.root, bg=t["fondo"])

        # ----- Encabezado: marca, conexión y tema -----
        encabezado = tk.Frame(self.frame_app, bg=t["superficie"])
        encabezado.pack(fill="x")
        fila = tk.Frame(encabezado, bg=t["superficie"])
        fila.pack(fill="x", padx=p(24), pady=p(12))

        marca = tk.Frame(fila, bg=t["superficie"])
        marca.pack(side="left")
        tk.Label(marca, text="COBOT", font=("Segoe UI Black", 18), fg=t["acento"],
                 bg=t["superficie"]).pack(anchor="w")
        tk.Label(marca, text="WALL-E CONTROL SYSTEM", font=(FUENTE, 8, "bold"), fg=t["apagado"],
                 bg=t["superficie"]).pack(anchor="w")

        f_tema = tk.Frame(fila, bg=t["superficie"])
        f_tema.pack(side="right")
        tk.Label(f_tema, text="TEMA", font=(FUENTE, 8, "bold"), fg=t["apagado"],
                 bg=t["superficie"]).pack(side="left", padx=(0, p(8)))
        self.combo_tema = ttk.Combobox(f_tema, values=list(TEMAS), width=17, state="readonly",
                                       font=(FUENTE, 10))
        self.combo_tema.set(self.nombre_tema)
        self.combo_tema.pack(side="left")
        self.combo_tema.bind("<<ComboboxSelected>>", lambda e: self.cambiar_tema(self.combo_tema.get()))

        f_con = tk.Frame(fila, bg=t["superficie"])
        f_con.pack(side="left", padx=p(48))
        tk.Label(f_con, text="PUERTO", font=(FUENTE, 8, "bold"), fg=t["apagado"],
                 bg=t["superficie"]).pack(side="left", padx=(0, p(8)))
        self.combo_ports = ttk.Combobox(f_con, values=self.obtener_puertos(), width=10,
                                        state="readonly", font=(FUENTE, 10))
        self.combo_ports.pack(side="left")
        if self.combo_ports['values']:
            self.combo_ports.current(0)

        fuente_chica = (FUENTE, 10, "bold")
        Boton(f_con, self, "↻", "secundario", 38, 32, fuente=(FUENTE, 13, "bold"),
              al_click=self.actualizar_puertos).pack(side="left", padx=(p(6), 0))
        self.btn_conectar = Boton(f_con, self, "CONECTAR", "primario", 112, 32, fuente=fuente_chica,
                                  al_click=self.conectar)
        self.btn_conectar.pack(side="left", padx=(p(14), 0))
        Boton(f_con, self, "DESCONECTAR", "secundario", 128, 32, fuente=fuente_chica,
              al_click=self.desconectar).pack(side="left", padx=(p(6), 0))
        self.lbl_estado = tk.Label(f_con, text="", font=(FUENTE, 9, "bold"), bg=t["superficie2"],
                                   padx=p(12), pady=p(6))
        self.lbl_estado.pack(side="left", padx=(p(14), 0))

        tk.Frame(self.frame_app, bg=t["borde"], height=1).pack(fill="x")

        # ----- Barra de secciones y sensor -----
        barra = tk.Frame(self.frame_app, bg=t["fondo"])
        barra.pack(fill="x", padx=p(24), pady=(p(10), 0))
        self.crear_tabs(barra)
        self.crear_indicador_sensor(barra)
        tk.Frame(self.frame_app, bg=t["borde"], height=1).pack(fill="x", padx=p(24))

        # ----- Contenedor de vistas -----
        self.container = tk.Frame(self.frame_app, bg=t["fondo"])
        self.container.pack(fill="both", expand=True, padx=p(24), pady=p(16))
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for nombre in ("PRINCIPAL", "SERVOS", "RUEDAS", "AUTO_CONTINUO"):
            frame = tk.Frame(self.container, bg=t["fondo"])
            frame.grid(row=0, column=0, sticky="nsew")
            self.frames[nombre] = frame

        self.construir_pantalla_principal()
        self.construir_pantalla_servos()
        self.construir_pantalla_ruedas()
        self.construir_pantalla_auto_continuo()

        self.mostrar_frame(self.modo_actual)
        self.refrescar_estado()

    def refrescar_estado(self):
        """Vuelve a pintar el estado actual (útil después de reconstruir la interfaz)."""
        self.set_estado_conexion(*self.estado_conexion)
        self.btn_conectar.set_habilitado(not self.conectando)
        self.actualizar_sensor(self.ultima_lectura)
        self.set_estado_auto_parada(self.auto_con_parada_activo)
        self.set_estado_auto_continuo(self.auto_continuo_activo)
        self._pintar_rutina_cabeza()

    def centrar(self, frame):
        centro = tk.Frame(frame, bg=self.tema["fondo"])
        centro.place(relx=0.5, rely=0.5, anchor="center")
        return centro

    def crear_tarjeta(self, parent, titulo, detalle=""):
        """Tarjeta con título. Devuelve (tarjeta, cuerpo): se coloca la tarjeta y se llena el cuerpo."""
        t, p = self.tema, self.px
        tarjeta = tk.Frame(parent, bg=t["superficie"], highlightthickness=1,
                           highlightbackground=t["borde"], highlightcolor=t["borde"])
        cabecera = tk.Frame(tarjeta, bg=t["superficie"])
        cabecera.pack(fill="x", padx=p(16), pady=(p(14), p(4)))
        tk.Frame(cabecera, bg=t["acento"], width=p(4), height=p(16)).pack(side="left", padx=(0, p(8)))
        tk.Label(cabecera, text=titulo, font=(FUENTE, 11, "bold"), fg=t["texto"],
                 bg=t["superficie"]).pack(side="left")
        if detalle:
            tk.Label(cabecera, text=detalle, font=(FUENTE, 9), fg=t["apagado"],
                     bg=t["superficie"]).pack(side="right", padx=(p(16), 0))
        cuerpo = tk.Frame(tarjeta, bg=t["superficie"])
        cuerpo.pack(fill="both", expand=True, padx=p(16), pady=(p(6), p(16)))
        return tarjeta, cuerpo

    # ----- Secciones (pestañas) -----
    def crear_tabs(self, parent):
        t, p = self.tema, self.px
        self.tabs = {}
        for modo, texto in (("PRINCIPAL", "PRINCIPAL"), ("SERVOS", "SERVOS"),
                            ("RUEDAS", "RUEDAS"), ("AUTO_CONTINUO", "AUTO CONTINUO")):
            celda = tk.Frame(parent, bg=t["fondo"])
            celda.pack(side="left", padx=(0, p(4)))
            etiqueta = tk.Label(celda, text=texto, font=(FUENTE, 11, "bold"), bg=t["fondo"],
                                fg=t["apagado"], padx=p(18), pady=p(10), cursor="hand2")
            etiqueta.pack()
            linea = tk.Frame(celda, bg=t["fondo"], height=p(3))
            linea.pack(fill="x")
            etiqueta.bind("<Button-1>", lambda e, m=modo: self.cambiar_modo(m))
            etiqueta.bind("<Enter>", lambda e, l=etiqueta: l.config(fg=t["texto"]))
            etiqueta.bind("<Leave>", lambda e: self.marcar_tab(self.modo_actual))
            self.tabs[modo] = (etiqueta, linea)

    def marcar_tab(self, modo):
        t = self.tema
        for nombre, (etiqueta, linea) in self.tabs.items():
            activo = nombre == modo
            etiqueta.config(fg=t["texto"] if activo else t["apagado"])
            linea.config(bg=t["acento"] if activo else t["fondo"])

    def cambiar_modo(self, nuevo_modo):
        if self.motores_en_movimiento or self.auto_con_parada_activo or self.auto_continuo_activo:
            messagebox.showwarning("¡ALERTA DE SEGURIDAD!",
                                   "Debes DETENER LAS RUEDAS por completo antes de cambiar de sección.")
            return
        self.modo_actual = nuevo_modo
        self.mostrar_frame(nuevo_modo)

    def mostrar_frame(self, modo):
        self.frames[modo].tkraise()
        self.marcar_tab(modo)

    # ----- Indicador del sensor -----
    def crear_indicador_sensor(self, parent):
        t, p = self.tema, self.px
        caja = tk.Frame(parent, bg=t["fondo"])
        caja.pack(side="right")
        tk.Label(caja, text="DISTANCIA", font=(FUENTE, 8, "bold"), fg=t["apagado"],
                 bg=t["fondo"]).pack(side="left", padx=(0, p(10)))
        self.lbl_distancia = tk.Label(caja, text="---", width=9, anchor="e",
                                      font=(FUENTE, 15, "bold"), fg=t["apagado"], bg=t["fondo"])
        self.lbl_distancia.pack(side="left")
        self.sensor_ancho, self.sensor_alto = p(120), p(8)
        self.barra_sensor = tk.Canvas(caja, width=self.sensor_ancho, height=self.sensor_alto,
                                      bg=t["fondo"], highlightthickness=0)
        self.barra_sensor.pack(side="left", padx=(p(12), 0))

    def actualizar_sensor(self, valor):
        """Muestra la distancia con color según el peligro. valor=None significa sin datos."""
        t = self.tema
        if valor is None:
            texto, color, fraccion = "---", t["apagado"], 0
        elif valor >= 999:                  # El Arduino envía 999 cuando no hay eco
            texto, color, fraccion = "> 400 cm", t["exito"], 1
        else:
            texto = f"{valor} cm"
            if valor <= DIST_FRENADO_CM:
                color = t["peligro"]
            elif valor <= DIST_AVISO_CM:
                color = t["aviso"]
            else:
                color = t["exito"]
            fraccion = min(valor, 200) / 200

        self.lbl_distancia.config(text=texto, fg=color)
        barra, ancho, alto = self.barra_sensor, self.sensor_ancho, self.sensor_alto
        barra.delete("all")
        barra.create_rectangle(0, 0, ancho, alto, fill=t["superficie2"], outline="")
        if fraccion > 0:
            barra.create_rectangle(0, 0, ancho * fraccion, alto, fill=color, outline="")
        marca = ancho * DIST_FRENADO_CM / 200       # Marca del límite de frenado
        barra.create_line(marca, 0, marca, alto, fill=t["peligro"], width=2)

    # =========================================================
    # SECCIÓN 1: PRINCIPAL
    # =========================================================
    def construir_pantalla_principal(self):
        centro = self.centrar(self.frames["PRINCIPAL"])
        servos = self.crear_panel_servos(centro, columnas=2)
        servos.grid(row=0, column=0, sticky="n")
        ruedas = self.crear_cruceta_ruedas(centro, 116, 88)
        ruedas.grid(row=0, column=1, sticky="n", padx=(self.px(16), 0), pady=self.px(8))

    # =========================================================
    # SECCIÓN 2: SERVOS
    # =========================================================
    def construir_pantalla_servos(self):
        centro = self.centrar(self.frames["SERVOS"])
        self.crear_panel_servos(centro, columnas=4, alto=68).pack()

    def crear_panel_servos(self, parent, columnas, ancho=208, alto=60):
        """Una tarjeta por servo. Todas tienen 2 filas de botones para que queden parejas."""
        p = self.px
        panel = tk.Frame(parent, bg=self.tema["fondo"])
        mitad = (ancho - HUECO) // 2
        for i, (titulo, detalle, lado_a_lado, botones) in enumerate(GRUPOS_SERVOS):
            tarjeta, cuerpo = self.crear_tarjeta(panel, titulo, detalle)
            tarjeta.grid(row=i // columnas, column=i % columnas, sticky="nsew", padx=p(8), pady=p(8))
            for n, (texto, mover, parar) in enumerate(botones):
                if lado_a_lado:
                    fila, col, span, w = 0, n, 1, mitad
                else:
                    fila, col, span, w = n, 0, 2, ancho
                Boton(cuerpo, self, texto, "secundario", w, alto, control=True,
                      al_presionar=lambda c=mover: self.enviar(c),
                      al_soltar=lambda c=parar: self.enviar(c)
                      ).grid(row=fila, column=col, columnspan=span,
                             padx=(p(HUECO) if col else 0, 0), pady=p(5))
            if titulo == "CABEZA":
                auto = Boton(cuerpo, self, self.TXT_RUTINA_OFF, "secundario", ancho, alto,
                             control=True, fuente=(FUENTE, 10, "bold"),
                             al_click=self.alternar_rutina_cabeza)
                auto.grid(row=1, column=0, columnspan=2, pady=p(5))
                self.botones_auto_cabeza.append(auto)
        for c in range(columnas):
            panel.grid_columnconfigure(c, weight=1, uniform="servos")
        return panel

    # =========================================================
    # SECCIÓN 3: RUEDAS
    # =========================================================
    def construir_pantalla_ruedas(self):
        centro = self.centrar(self.frames["RUEDAS"])
        self.crear_cruceta_ruedas(centro, 160, 116, fuente=(FUENTE, 13, "bold"),
                                  tam_icono=26).pack()

    def crear_cruceta_ruedas(self, parent, ancho, alto, fuente=None, tam_icono=20):
        """Cruceta de dirección + botón de modo auto. Devuelve la tarjeta."""
        t, p = self.tema, self.px
        tarjeta, cuerpo = self.crear_tarjeta(parent, "TRACCIÓN", "mantén presionado")

        cruceta = tk.Frame(cuerpo, bg=t["superficie"])
        cruceta.pack()
        for i in range(3):
            cruceta.grid_columnconfigure(i, minsize=p(ancho) + 2 * p(HUECO))
            cruceta.grid_rowconfigure(i, minsize=p(alto) + 2 * p(HUECO))

        def boton(texto, icono, fila, col, estilo="secundario", **acciones):
            Boton(cruceta, self, texto, estilo, ancho, alto, fuente=fuente, icono=icono,
                  tam_icono=tam_icono, control=True,
                  **acciones).grid(row=fila, column=col, padx=p(HUECO), pady=p(HUECO))

        boton("AVANZAR", "▲", 0, 1,
              al_presionar=self.presionar_avanzar_manual, al_soltar=self.soltar_avanzar_manual)
        boton("IZQUIERDA", "◀", 1, 0,
              al_presionar=lambda: self.enviar('L'), al_soltar=lambda: self.enviar('S'))
        boton("STOP", "■", 1, 1, "peligro", al_presionar=self.parar_ruedas)
        boton("DERECHA", "▶", 1, 2,
              al_presionar=lambda: self.enviar('R'), al_soltar=lambda: self.enviar('S'))
        boton("ATRÁS", "▼", 2, 1,
              al_presionar=lambda: self.enviar('B'), al_soltar=lambda: self.enviar('S'))

        # El botón de modo auto existe en dos pantallas; el texto se actualiza en ambos
        auto = Boton(cuerpo, self, self.TXT_AUTO_OFF, "primario", 3 * ancho + 4 * HUECO, 52,
                     control=True, al_click=self.toggle_auto_con_parada)
        auto.pack(pady=(p(12), 0))
        self.botones_auto_parada.append(auto)
        return tarjeta

    # =========================================================
    # SECCIÓN 4: AUTO CONTINUO
    # =========================================================
    def construir_pantalla_auto_continuo(self):
        t, p = self.tema, self.px
        centro = self.centrar(self.frames["AUTO_CONTINUO"])
        tarjeta, cuerpo = self.crear_tarjeta(centro, "MODO AUTOMÁTICO CONTINUO",
                                             f"frena a {DIST_FRENADO_CM} cm")
        tarjeta.pack()

        tk.Label(cuerpo, justify="left", font=(FUENTE, 11), fg=t["apagado"], bg=t["superficie"],
                 text="El robot avanza de forma continua hasta que presiones DETENER\n"
                      f"o hasta que el sensor detecte un obstáculo a {DIST_FRENADO_CM} cm o menos."
                 ).pack(anchor="w", pady=(p(4), p(18)))

        fila = tk.Frame(cuerpo, bg=t["superficie"])
        fila.pack()
        Boton(fila, self, "▶   AVANZAR CONTINUO", "primario", 270, 72, control=True,
              fuente=(FUENTE, 12, "bold"),
              al_click=self.iniciar_auto_continuo).pack(side="left", padx=(0, p(10)))
        Boton(fila, self, "■   DETENER", "peligro", 200, 72, control=True,
              fuente=(FUENTE, 12, "bold"),
              al_presionar=self.detener_auto_continuo).pack(side="left")

        self.lbl_auto_estado = tk.Label(cuerpo, font=(FUENTE, 10, "bold"), bg=t["superficie"])
        self.lbl_auto_estado.pack(anchor="w", pady=(p(16), 0))

    # =========================================================
    # LÓGICA DE TRACCIÓN
    # =========================================================
    def obstaculo_cerca(self):
        return 0 < self.distancia_sensor <= DIST_FRENADO_CM

    def enviar(self, char_cmd):
        """Envía un comando al Arduino. Devuelve True si se envió."""
        if not (self.arduino and self.arduino.is_open):
            return False
        # No arrancar hacia adelante si ya hay un obstáculo delante
        if char_cmd == 'F' and self.obstaculo_cerca():
            return False
        try:
            self.arduino.write(char_cmd.encode('ascii'))
        except (serial.SerialException, OSError) as e:
            print("Error de envío:", e)
            self.perder_conexion("No se pudo enviar al robot (¿se apagó el Bluetooth?).")
            return False

        if char_cmd in ('F', 'B', 'L', 'R'):
            self.direccion = char_cmd
        elif char_cmd in ('S', 'X'):
            self.direccion = None
        if char_cmd in ('1', '2', '3', 'X'):
            self.terminar_rutina_cabeza()   # Mover la cabeza a mano cancela la rutina automática
        return True

    def presionar_avanzar_manual(self):
        if not self.auto_con_parada_activo:
            self.enviar('F')

    def soltar_avanzar_manual(self):
        if not self.auto_con_parada_activo:
            self.enviar('S')

    def parar_ruedas(self):
        """Botón STOP: detiene la tracción en cualquier modo."""
        if self.auto_con_parada_activo:
            self.desactivar_auto_con_parada()
        elif self.auto_continuo_activo:
            self.detener_auto_continuo()
        else:
            self.enviar('S')

    def set_estado_auto_parada(self, activo):
        self.auto_con_parada_activo = activo
        for btn in self.botones_auto_parada:
            btn.set_estilo("exito" if activo else "primario")
            btn.set_texto(self.TXT_AUTO_ON if activo else self.TXT_AUTO_OFF)

    def set_estado_auto_continuo(self, activo):
        self.auto_continuo_activo = activo
        t = self.tema
        if activo:
            self.lbl_auto_estado.config(text="●  ESTADO: AVANZANDO", fg=t["exito"])
        else:
            self.lbl_auto_estado.config(text="●  ESTADO: EN ESPERA", fg=t["apagado"])

    def toggle_auto_con_parada(self):
        if self.auto_con_parada_activo:
            self.desactivar_auto_con_parada()
        elif self.enviar('F'):
            self.set_estado_auto_parada(True)

    def desactivar_auto_con_parada(self):
        self.set_estado_auto_parada(False)
        self.enviar('S')

    def iniciar_auto_continuo(self):
        if self.enviar('F'):
            self.set_estado_auto_continuo(True)

    def detener_auto_continuo(self):
        self.set_estado_auto_continuo(False)
        self.enviar('S')

    # ----- Rutina automática de la cabeza -----
    def alternar_rutina_cabeza(self):
        """Botón AUTO de la cabeza: inicia la rutina o, si ya está en marcha, la cancela."""
        if self.rutina_cabeza_restante > 0:
            self.enviar('3')                # El Arduino cancela la rutina y detiene la cabeza
        elif self.enviar('A'):
            self.rutina_cabeza_restante = RUTINA_CABEZA_S
            self._pintar_rutina_cabeza()
            self._id_rutina = self.root.after(1000, self._tick_rutina_cabeza)

    def _tick_rutina_cabeza(self):
        self._id_rutina = None
        if self.rutina_cabeza_restante <= 0:
            return                          # Temporizador sobrante: la rutina ya había terminado
        self.rutina_cabeza_restante -= 1
        if self.rutina_cabeza_restante > 0:
            self._id_rutina = self.root.after(1000, self._tick_rutina_cabeza)
        self._pintar_rutina_cabeza()

    def terminar_rutina_cabeza(self):
        """Marca la rutina como terminada (acabó sola, se canceló o se movió la cabeza a mano)."""
        if self._id_rutina is not None:
            self.root.after_cancel(self._id_rutina)
            self._id_rutina = None
        if self.rutina_cabeza_restante:
            self.rutina_cabeza_restante = 0
            self._pintar_rutina_cabeza()

    def _pintar_rutina_cabeza(self):
        restante = self.rutina_cabeza_restante
        for btn in self.botones_auto_cabeza:
            if restante > 0:
                btn.set_estilo("peligro")
                btn.set_texto(f"■   CANCELAR   ·   {restante} s")
            else:
                btn.set_estilo("secundario")
                btn.set_texto(self.TXT_RUTINA_OFF)

    def frenar_por_obstaculo(self):
        """Freno de emergencia. Solo actúa si el robot va hacia adelante (marcha atrás libre)."""
        if self.auto_con_parada_activo:
            self.desactivar_auto_con_parada()
        elif self.auto_continuo_activo:
            self.detener_auto_continuo()
        elif self.direccion == 'F':
            self.enviar('S')

    # =========================================================
    # CONEXIÓN SERIAL
    # =========================================================
    def obtener_puertos(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def actualizar_puertos(self):
        puertos = self.obtener_puertos()
        self.combo_ports['values'] = puertos
        if puertos:
            self.combo_ports.current(0)

    def set_estado_conexion(self, estado, detalle=""):
        self.estado_conexion = (estado, detalle)
        texto, clave_color = self.ESTADOS_CONEXION[estado]
        if detalle:
            texto += f"  ·  {detalle}"
        self.lbl_estado.config(text=f"●  {texto}", fg=self.tema[clave_color])
        self.actualizar_habilitacion()

    def actualizar_habilitacion(self):
        """Los botones de control solo funcionan con el robot conectado."""
        conectado = bool(self.arduino and self.arduino.is_open)
        for boton in self.botones_control:
            boton.set_habilitado(conectado)

    def conectar(self):
        port = self.combo_ports.get()
        if not port or self.conectando:
            return
        if self.arduino and self.arduino.is_open:
            self.cerrar_conexion()

        # Abrir un COM Bluetooth puede tardar varios segundos: se hace fuera del hilo de la interfaz
        self.conectando = True
        self.btn_conectar.set_habilitado(False)
        self.set_estado_conexion("conectando")
        threading.Thread(target=self._abrir_puerto, args=(port,), daemon=True).start()

    def _abrir_puerto(self, port):
        try:
            ser = serial.Serial(port, BAUDIOS, timeout=0.1, write_timeout=1)
            self.cola.put(("CONECTADO", (port, ser)))
        except Exception as e:
            self.cola.put(("FALLO", (port, e)))

    def _iniciar_lectura(self, ser):
        self.stop_lectura = threading.Event()
        self.hilo_lectura = threading.Thread(target=self._leer_serial, args=(ser, self.stop_lectura),
                                             daemon=True)
        self.hilo_lectura.start()

    def _leer_serial(self, ser, stop):
        """Hilo lector: NUNCA toca la interfaz, solo mete datos en la cola."""
        buffer = b""
        while not stop.is_set():
            try:
                datos = ser.read(ser.in_waiting or 1)
            except (serial.SerialException, OSError):
                if not stop.is_set():
                    self.cola.put(("ERROR", None))
                return
            if not datos:
                continue
            buffer += datos
            if len(buffer) > 1024:          # Protección ante basura sin saltos de línea
                buffer = buffer[-128:]
            while b"\n" in buffer:
                linea, buffer = buffer.split(b"\n", 1)
                m = RE_DIST.search(linea)
                if m:
                    self.cola.put(("DIST", int(m.group(1))))

    def procesar_cola(self):
        """Corre en el hilo de la interfaz: aplica lo que dejaron los otros hilos."""
        ultima_dist = None
        try:
            while True:
                tipo, valor = self.cola.get_nowait()
                if tipo == "DIST":
                    ultima_dist = valor         # Solo importa la lectura más reciente
                elif tipo == "CONECTADO":
                    self._conexion_establecida(*valor)
                elif tipo == "FALLO":
                    self._conexion_fallida(*valor)
                elif tipo == "ERROR":
                    self.perder_conexion("Se perdió la comunicación con el robot.")
        except queue.Empty:
            pass

        if ultima_dist is not None and self.arduino:
            self.distancia_sensor = ultima_dist
            self.ultima_lectura = ultima_dist
            self.actualizar_sensor(ultima_dist)
            if self.obstaculo_cerca():
                self.frenar_por_obstaculo()

        self.root.after(INTERVALO_COLA_MS, self.procesar_cola)

    def _conexion_establecida(self, port, ser):
        self.conectando = False
        self.btn_conectar.set_habilitado(True)
        self.arduino = ser
        self.distancia_sensor = 999
        self.ultima_lectura = None
        self.direccion = None
        self.actualizar_sensor(None)
        self._iniciar_lectura(ser)
        self.set_estado_conexion("conectado", port)

    def _conexion_fallida(self, port, error):
        self.conectando = False
        self.btn_conectar.set_habilitado(True)
        self.set_estado_conexion("desconectado")
        messagebox.showerror("Error", f"No se pudo conectar a {port}.\n\nDetalle: {error}")

    def cerrar_conexion(self, enviar_parada=True):
        """Cierra el puerto de forma ordenada y resetea el estado."""
        ser, self.arduino = self.arduino, None
        if self.stop_lectura:
            self.stop_lectura.set()
        if ser:
            try:
                if enviar_parada and ser.is_open:
                    ser.write(b'X')             # Frena motores y servos
            except (serial.SerialException, OSError):
                pass
            if self.hilo_lectura and self.hilo_lectura.is_alive():
                self.hilo_lectura.join(timeout=0.5)
            try:
                ser.close()
            except (serial.SerialException, OSError):
                pass
        self.hilo_lectura = None
        self.stop_lectura = None

        self.direccion = None
        self.terminar_rutina_cabeza()
        self.set_estado_auto_continuo(False)
        self.set_estado_auto_parada(False)
        self.distancia_sensor = 999
        self.ultima_lectura = None
        self.actualizar_sensor(None)
        self.set_estado_conexion("desconectado")

    def desconectar(self):
        if self.arduino:
            self.cerrar_conexion()

    def perder_conexion(self, motivo):
        """La comunicación se cayó: se limpia todo y se avisa una sola vez."""
        if not self.arduino:
            return
        self.cerrar_conexion(enviar_parada=False)
        messagebox.showwarning("Conexión perdida", motivo)

    def al_cerrar(self):
        if self.arduino:
            self.cerrar_conexion()
        self.root.destroy()


if __name__ == "__main__":
    try:                                    # Texto nítido en pantallas con escala (125 %, 150 %…)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = WallEControlApp(root)
    root.mainloop()
