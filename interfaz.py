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
INTERVALO_COLA_MS = 50        # Cada cuánto la interfaz revisa los datos del sensor
RE_DIST = re.compile(rb"DIST:(\d+)")


class WallEControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SISTEMA DE CONTROL GENERAL - COBOT WALL-E")
        self.root.geometry("1280x800")

        # --- PALETA WALL-E INDUSTRIAL ---
        self.C_BG_MAIN = "#22242B"
        self.C_BG_BOX = "#2E313D"
        self.C_ORANGE = "#E67E22"
        self.C_YELLOW = "#F1C40F"
        self.C_RED = "#C0392B"
        self.C_TEXT = "#ECF0F1"
        self.C_CYAN = "#00D2D3"
        self.C_GREEN = "#27AE60"

        self.root.configure(bg="#000000")
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
        self.auto_con_parada_activo = False
        self.auto_continuo_activo = False
        self.botones_auto_parada = []       # El botón de modo auto aparece en 2 pantallas

        self.construir_splash()
        self.construir_interfaz()

        self.root.protocol("WM_DELETE_WINDOW", self.al_cerrar)
        self.root.after(INTERVALO_COLA_MS, self.procesar_cola)

        self.paso_animacion = 0
        self.root.after(300, self.ejecutar_animacion_entrada)

    @property
    def motores_en_movimiento(self):
        return self.direccion is not None

    # =========================================================
    # PANTALLA DE ENTRADA
    # =========================================================
    def construir_splash(self):
        self.frame_splash = tk.Frame(self.root, bg="#000000")
        self.frame_splash.pack(fill="both", expand=True)

        tk.Label(self.frame_splash, text="COBOT", fg="#E50914", bg="#000000",
                 font=("Impact", 80, "bold")).pack(expand=True, pady=(80, 0))
        tk.Label(self.frame_splash, text="WALL-E CONTROL SYSTEM", fg="#E50914", bg="#000000",
                 font=("Arial", 14, "bold")).pack(pady=(0, 20))

        self.lbl_status = tk.Label(self.frame_splash, text="INICIANDO SISTEMAS...",
                                   fg="#8C8C8C", bg="#000000", font=("Arial", 11))
        self.lbl_status.pack(pady=5)

        style = ttk.Style()
        style.theme_use('default')
        style.configure("Red.Horizontal.TProgressbar", background='#E50914',
                        troughcolor='#141414', bordercolor='#000000')

        self.progress = ttk.Progressbar(self.frame_splash, length=500, mode='determinate',
                                        style="Red.Horizontal.TProgressbar")
        self.progress.pack(pady=(0, 60))

    def ejecutar_animacion_entrada(self):
        pasos = [
            (20, "Cargando protocolo de transmisión..."),
            (45, "Inicializando módulos Bluetooth..."),
            (70, "Calibrando servos y sensores..."),
            (90, "Configurando controles e interfaz..."),
            (100, "¡SISTEMAS LISTOS!"),
        ]
        if self.paso_animacion < len(pasos):
            p, texto = pasos[self.paso_animacion]
            self.progress['value'] = p
            self.lbl_status.config(text=texto)
            self.paso_animacion += 1
            self.root.after(700, self.ejecutar_animacion_entrada)
        else:
            self.root.after(500, self.transicion_a_principal)

    def transicion_a_principal(self):
        self.frame_splash.destroy()
        self.root.configure(bg=self.C_BG_MAIN)
        self.frame_app.pack(fill="both", expand=True)

    # =========================================================
    # ESTRUCTURA DE LA INTERFAZ
    # =========================================================
    def construir_interfaz(self):
        self.frame_app = tk.Frame(self.root, bg=self.C_BG_MAIN)

        # --- Barra superior ---
        self.frame_top = tk.Frame(self.frame_app, bg=self.C_BG_BOX, padx=15, pady=10)
        self.frame_top.pack(fill="x", side="top")

        f_con = tk.Frame(self.frame_top, bg=self.C_BG_BOX)
        f_con.pack(side="left")

        tk.Label(f_con, text="PUERTO:", fg=self.C_YELLOW, bg=self.C_BG_BOX,
                 font=("Arial", 11, "bold")).pack(side="left", padx=5)
        self.combo_ports = ttk.Combobox(f_con, values=self.obtener_puertos(), width=12,
                                        font=("Arial", 10), state="readonly")
        self.combo_ports.pack(side="left", padx=5)
        if self.combo_ports['values']:
            self.combo_ports.current(0)

        tk.Button(f_con, text="🔄", bg=self.C_ORANGE, fg=self.C_TEXT, font=("Arial", 10, "bold"),
                  command=self.actualizar_puertos).pack(side="left", padx=3)
        self.btn_conectar = tk.Button(f_con, text="CONECTAR", bg=self.C_GREEN, fg=self.C_TEXT,
                                      font=("Arial", 10, "bold"), padx=10, command=self.conectar)
        self.btn_conectar.pack(side="left", padx=5)
        tk.Button(f_con, text="DESCONECTAR", bg=self.C_RED, fg=self.C_TEXT,
                  font=("Arial", 10, "bold"), padx=10,
                  command=self.desconectar).pack(side="left", padx=5)

        self.lbl_estado = tk.Label(f_con, text="● DESCONECTADO", fg="#8C8C8C", bg=self.C_BG_BOX,
                                   font=("Arial", 10, "bold"))
        self.lbl_estado.pack(side="left", padx=10)

        f_nav = tk.Frame(self.frame_top, bg=self.C_BG_BOX)
        f_nav.pack(side="left", padx=30)
        self.crear_btn_nav(f_nav, "1. PRINCIPAL (TODO)", "PRINCIPAL")
        self.crear_btn_nav(f_nav, "2. SERVOS", "SERVOS")
        self.crear_btn_nav(f_nav, "3. RUEDAS", "RUEDAS")
        self.crear_btn_nav(f_nav, "4. AUTO CONTINUO", "AUTO_CONTINUO")

        self.lbl_distancia = tk.Label(self.frame_top, text="SENSOR: --- cm", fg=self.C_CYAN,
                                      bg=self.C_BG_BOX, font=("Arial", 13, "bold"))
        self.lbl_distancia.pack(side="right", padx=15)

        # --- Contenedor de vistas ---
        self.container = tk.Frame(self.frame_app, bg=self.C_BG_MAIN)
        self.container.pack(fill="both", expand=True, padx=20, pady=20)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for nombre in ("PRINCIPAL", "SERVOS", "RUEDAS", "AUTO_CONTINUO"):
            frame = tk.Frame(self.container, bg=self.C_BG_MAIN)
            frame.grid(row=0, column=0, sticky="nsew")
            self.frames[nombre] = frame

        self.construir_pantalla_principal()
        self.construir_pantalla_servos()
        self.construir_pantalla_ruedas()
        self.construir_pantalla_auto_continuo()
        self.mostrar_frame("PRINCIPAL")

    def crear_btn_nav(self, parent, texto, modo):
        tk.Button(parent, text=texto, bg="#1A1C23", fg=self.C_TEXT, font=("Arial", 11, "bold"),
                  command=lambda: self.cambiar_modo(modo), padx=12, pady=6).pack(side="left", padx=5)

    def cambiar_modo(self, nuevo_modo):
        if self.motores_en_movimiento or self.auto_con_parada_activo or self.auto_continuo_activo:
            messagebox.showwarning("¡ALERTA DE SEGURIDAD!",
                                   "Debes DETENER LAS RUEDAS por completo antes de cambiar de sección.")
            return
        self.modo_actual = nuevo_modo
        self.mostrar_frame(nuevo_modo)

    def mostrar_frame(self, modo):
        self.frames[modo].tkraise()

    # =========================================================
    # SECCIÓN 1: PRINCIPAL
    # =========================================================
    def construir_pantalla_principal(self):
        f = self.frames["PRINCIPAL"]
        f.grid_rowconfigure(0, weight=1)
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=1)

        f_servos = tk.Frame(f, bg=self.C_BG_MAIN)
        f_servos.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.crear_grupo_servos_ordenados(f_servos)

        f_ruedas = tk.Frame(f, bg=self.C_BG_MAIN)
        f_ruedas.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.crear_cruceta_ruedas(f_ruedas)

    # =========================================================
    # SECCIÓN 2: SERVOS
    # =========================================================
    def construir_pantalla_servos(self):
        f = self.frames["SERVOS"]
        f.grid_rowconfigure(0, weight=1)
        f.grid_columnconfigure(0, weight=1)

        panel = tk.Frame(f, bg=self.C_BG_MAIN)
        panel.grid(row=0, column=0, sticky="nsew")
        self.crear_grupo_servos_ordenados(panel)

    def crear_panel_servo(self, grid, col, titulo, color_titulo, filas=2):
        panel = tk.LabelFrame(grid, text=titulo, fg=color_titulo, bg=self.C_BG_BOX,
                              font=("Arial", 11, "bold"), padx=10, pady=10)
        panel.grid(row=0, column=col, sticky="nsew", padx=4, pady=8)
        for i in range(filas):
            panel.grid_rowconfigure(i, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        return panel

    def crear_grupo_servos_ordenados(self, parent):
        grid = tk.Frame(parent, bg=self.C_BG_MAIN)
        grid.pack(fill="both", expand=True)
        for col in range(4):
            grid.grid_columnconfigure(col, weight=1)
        grid.grid_rowconfigure(0, weight=1)

        # Brazo izquierdo (pin 8)
        f8 = self.crear_panel_servo(grid, 0, " BRAZO IZQ (8) ", self.C_YELLOW)
        self.crear_btn_servo_presion_grid(f8, "◀ SUBIR IZQ", '4', '6', 0, self.C_YELLOW)
        self.crear_btn_servo_presion_grid(f8, "BAJAR IZQ ▶", '5', '6', 1, self.C_ORANGE)

        # Ambos brazos
        f_both = self.crear_panel_servo(grid, 1, " AMBOS BRAZOS ", "#2ECC71")
        self.crear_btn_servo_presion_grid(f_both, "🙌 SUBIR AMBOS", 'U', 'N', 0, "#2ECC71")
        self.crear_btn_servo_presion_grid(f_both, "👇 BAJAR AMBOS", 'D', 'N', 1, self.C_GREEN)

        # Cabeza (pin 9)
        f9 = self.crear_panel_servo(grid, 2, " CABEZA (9) ", self.C_CYAN, filas=3)
        self.crear_btn_servo_presion_grid(f9, "◀ GIRAR IZQ", '1', '3', 0, self.C_YELLOW)
        self.crear_btn_servo_presion_grid(f9, "GIRAR DER ▶", '2', '3', 1, self.C_ORANGE)
        tk.Button(f9, text="🤖 AUTO (10s)", bg="#8E44AD", fg=self.C_TEXT, font=("Arial", 10, "bold"),
                  command=lambda: self.enviar('A')).grid(row=2, column=0, sticky="nsew", pady=4)

        # Brazo derecho (pin 10)
        f10 = self.crear_panel_servo(grid, 3, " BRAZO DER (10) ", self.C_YELLOW)
        self.crear_btn_servo_presion_grid(f10, "◀ SUBIR DER", '7', '9', 0, self.C_YELLOW)
        self.crear_btn_servo_presion_grid(f10, "BAJAR DER ▶", '8', '9', 1, self.C_ORANGE)

    def crear_btn_servo_presion_grid(self, parent, texto, cmd_mover, cmd_parar, row, color):
        btn = tk.Button(parent, text=texto, bg=color,
                        fg="#1A1C23" if color == self.C_YELLOW else self.C_TEXT,
                        font=("Arial", 11, "bold"))
        btn.grid(row=row, column=0, sticky="nsew", pady=4)
        btn.bind("<ButtonPress-1>", lambda e: self.enviar(cmd_mover))
        btn.bind("<ButtonRelease-1>", lambda e: self.enviar(cmd_parar))

    # =========================================================
    # SECCIÓN 3: RUEDAS
    # =========================================================
    def construir_pantalla_ruedas(self):
        f = self.frames["RUEDAS"]
        f.grid_rowconfigure(0, weight=1)
        f.grid_columnconfigure(0, weight=1)
        self.crear_cruceta_ruedas(f)

    def crear_btn_rueda(self, parent, texto, row, col, cmd_mover, cmd_parar):
        btn = tk.Button(parent, text=texto, bg=self.C_ORANGE, fg=self.C_TEXT, font=("Arial", 14, "bold"))
        btn.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
        btn.bind("<ButtonPress-1>", lambda e: cmd_mover())
        btn.bind("<ButtonRelease-1>", lambda e: cmd_parar())

    def crear_cruceta_ruedas(self, parent):
        grid = tk.Frame(parent, bg=self.C_BG_MAIN)
        grid.pack(fill="both", expand=True, padx=10, pady=10)
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1)
            grid.grid_rowconfigure(i, weight=1)

        self.crear_btn_rueda(grid, "▲\nAVANZAR", 0, 1,
                             self.presionar_avanzar_manual, self.soltar_avanzar_manual)
        self.crear_btn_rueda(grid, "◄ IZQUIERDA", 1, 0,
                             lambda: self.enviar('L'), lambda: self.enviar('S'))
        self.crear_btn_rueda(grid, "DERECHA ►", 1, 2,
                             lambda: self.enviar('R'), lambda: self.enviar('S'))
        self.crear_btn_rueda(grid, "▼\nATRAS", 2, 1,
                             lambda: self.enviar('B'), lambda: self.enviar('S'))

        # El botón de modo auto existe en dos pantallas; el texto se actualiza en ambos
        btn_auto = tk.Button(grid, text=self.TXT_AUTO_OFF, bg=self.C_YELLOW, fg="#1A1C23",
                             font=("Arial", 12, "bold"), command=self.toggle_auto_con_parada)
        btn_auto.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)
        self.botones_auto_parada.append(btn_auto)

    # =========================================================
    # SECCIÓN 4: AUTO CONTINUO
    # =========================================================
    def construir_pantalla_auto_continuo(self):
        f = self.frames["AUTO_CONTINUO"]
        f.grid_rowconfigure(0, weight=1)
        f.grid_columnconfigure(0, weight=1)

        box = tk.Frame(f, bg=self.C_BG_BOX, padx=30, pady=30)
        box.grid(row=0, column=0, sticky="nsew", padx=40, pady=40)
        box.grid_rowconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=2)
        box.grid_rowconfigure(2, weight=2)
        box.grid_columnconfigure(0, weight=1)

        tk.Label(box, text="MODO AUTOMÁTICO CONTINUO\nEl robot avanza continuamente hasta presionar Detener.",
                 fg=self.C_TEXT, bg=self.C_BG_BOX, font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="nsew")

        tk.Button(box, text="▶ AVANZAR CONTINUO", bg=self.C_ORANGE, fg=self.C_TEXT,
                  font=("Arial", 16, "bold"),
                  command=self.iniciar_auto_continuo).grid(row=1, column=0, sticky="nsew", pady=15)
        tk.Button(box, text="⏹ DETENER Y PARAR", bg=self.C_RED, fg=self.C_TEXT,
                  font=("Arial", 16, "bold"),
                  command=self.detener_auto_continuo).grid(row=2, column=0, sticky="nsew", pady=15)

    # =========================================================
    # LÓGICA DE TRACCIÓN
    # =========================================================
    TXT_AUTO_OFF = "🤖 MODO AUTO\n(1 Toque / Parada)"
    TXT_AUTO_ON = "🤖 AUTO ACTIVO\n(Avanzando...)"

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
        return True

    def presionar_avanzar_manual(self):
        if not self.auto_con_parada_activo:
            self.enviar('F')

    def soltar_avanzar_manual(self):
        if not self.auto_con_parada_activo:
            self.enviar('S')

    def set_estado_auto_parada(self, activo):
        self.auto_con_parada_activo = activo
        for btn in self.botones_auto_parada:
            if activo:
                btn.config(bg=self.C_GREEN, fg=self.C_TEXT, text=self.TXT_AUTO_ON)
            else:
                btn.config(bg=self.C_YELLOW, fg="#1A1C23", text=self.TXT_AUTO_OFF)

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
            self.auto_continuo_activo = True

    def detener_auto_continuo(self):
        self.auto_continuo_activo = False
        self.enviar('S')

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

    def set_estado_conexion(self, texto, color):
        self.lbl_estado.config(text=texto, fg=color)

    def conectar(self):
        port = self.combo_ports.get()
        if not port or self.conectando:
            return
        if self.arduino and self.arduino.is_open:
            self.cerrar_conexion()

        # Abrir un COM Bluetooth puede tardar varios segundos: se hace fuera del hilo de la interfaz
        self.conectando = True
        self.btn_conectar.config(state="disabled")
        self.set_estado_conexion("● CONECTANDO...", self.C_YELLOW)
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
            self.lbl_distancia.config(text=f"SENSOR: {ultima_dist} cm")
            if self.obstaculo_cerca():
                self.frenar_por_obstaculo()

        self.root.after(INTERVALO_COLA_MS, self.procesar_cola)

    def _conexion_establecida(self, port, ser):
        self.conectando = False
        self.btn_conectar.config(state="normal")
        self.arduino = ser
        self.distancia_sensor = 999
        self.direccion = None
        self._iniciar_lectura(ser)
        self.set_estado_conexion(f"● CONECTADO ({port})", self.C_GREEN)

    def _conexion_fallida(self, port, error):
        self.conectando = False
        self.btn_conectar.config(state="normal")
        self.set_estado_conexion("● DESCONECTADO", "#8C8C8C")
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
        self.auto_continuo_activo = False
        self.set_estado_auto_parada(False)
        self.distancia_sensor = 999
        self.lbl_distancia.config(text="SENSOR: --- cm")
        self.set_estado_conexion("● DESCONECTADO", "#8C8C8C")

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
    root = tk.Tk()
    app = WallEControlApp(root)
    root.mainloop()
