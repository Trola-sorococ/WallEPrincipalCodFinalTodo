#include <Servo.h>

// Declaración de Servos (360° / Rotación Continua)
Servo servoBrazoIzq; // Pin 8 (Invertido)
Servo servoCabeza;   // Pin 9
Servo servoBrazoDer; // Pin 10

// Pines L298N (Motores DC)
const int ENA = 3;   // PWM (Timer2) - lado izquierdo
const int IN1 = 4;
const int IN2 = 5;
const int IN3 = 6;
const int IN4 = 7;
const int ENB = 11;  // PWM (Timer2) - lado derecho. No usar el pin 9: la librería Servo lo ocupa (Timer1)

// Pines Sensor HC-SR04 Frontal
const int ECHO_PIN = 13;
const int TRIG_PIN = 12;

int velocidadMotores = 200;
unsigned long ultimoUltrasonico = 0;

// Rutina automática de la cabeza (no bloqueante: usa millis() en lugar de delay())
const unsigned long TRAMO_CABEZA_MS = 5000; // Duración de cada tramo (2 tramos = 10 s)
byte faseCabeza = 0;                        // 0 = inactiva, 1 = primer tramo, 2 = segundo tramo
unsigned long inicioFaseCabeza = 0;

void setup() {
  Serial.begin(9600);

  // Configurar Pines L298N
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  pinMode(ENB, OUTPUT);

  // Configurar Pines Ultrasónico
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // Conectar Servos
  servoBrazoIzq.attach(8);
  servoCabeza.attach(9);
  servoBrazoDer.attach(10);

  detenerServos();
  frenarMotores();
}

void loop() {
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    procesarComando(cmd);
  }

  actualizarAutoCabeza();   // Avanza la rutina de la cabeza sin bloquear el resto

  if (millis() - ultimoUltrasonico > 80) {
    ultimoUltrasonico = millis();
    long distancia = medirDistancia();
    Serial.print("DIST:");
    Serial.println(distancia);
  }
}

void procesarComando(char cmd) {
  switch (cmd) {
    // --- MOTORES TRACCIÓN ---
    case 'F': moverAvanzar(); break;
    case 'B': moverRetroceder(); break;
    case 'L': moverIzquierda(); break;
    case 'R': moverDerecha(); break;
    case 'S': frenarMotores(); break;

    // --- BRAZO IZQ (PIN 8 - INVERTIDO EN HARDWARE) ---
    case '4': servoBrazoIzq.write(40);  break; // Subir (Invertido)
    case '5': servoBrazoIzq.write(140); break; // Bajar (Invertido)
    case '6': servoBrazoIzq.write(90);  break; // Detener

    // --- CABEZA (PIN 9) --- (moverla a mano cancela la rutina automática)
    case '1': cancelarAutoCabeza(); servoCabeza.write(140); break;
    case '2': cancelarAutoCabeza(); servoCabeza.write(40);  break;
    case '3': cancelarAutoCabeza(); servoCabeza.write(90);  break;

    // --- BRAZO DER (PIN 10) ---
    case '7': servoBrazoDer.write(140); break;
    case '8': servoBrazoDer.write(40);  break;
    case '9': servoBrazoDer.write(90);  break;

    // --- AMBOS BRAZOS SIMULTÁNEOS ---
    case 'U': 
      servoBrazoIzq.write(40);  // Pin 8 Invertido para subir
      servoBrazoDer.write(140); // Pin 10 Normal para subir
      break;
    case 'D': 
      servoBrazoIzq.write(140); // Pin 8 Invertido para bajar
      servoBrazoDer.write(40);  // Pin 10 Normal para bajar
      break;
    case 'N': 
      servoBrazoIzq.write(90);
      servoBrazoDer.write(90);
      break;

    // --- MODO AUTOMÁTICO CABEZA ---
    case 'A': iniciarAutoCabeza(); break;

    // FRENAR TODO
    case 'X':
      frenarMotores();
      detenerServos();
      break;
  }
}

// --- RUTINA AUTOMÁTICA DE LA CABEZA (sin delay: el robot sigue respondiendo) ---

void iniciarAutoCabeza() {
  if (faseCabeza != 0) return;       // Ya está en marcha
  faseCabeza = 1;
  inicioFaseCabeza = millis();
  servoCabeza.write(135);
}

void cancelarAutoCabeza() {
  faseCabeza = 0;
}

void actualizarAutoCabeza() {        // Se llama en cada vuelta del loop()
  if (faseCabeza == 0) return;
  if (millis() - inicioFaseCabeza < TRAMO_CABEZA_MS) return;

  if (faseCabeza == 1) {
    servoCabeza.write(45);
    faseCabeza = 2;
    inicioFaseCabeza = millis();
  } else {
    servoCabeza.write(90);
    faseCabeza = 0;
  }
}

void moverAvanzar() {
  digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
  digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
  analogWrite(ENA, velocidadMotores);
  analogWrite(ENB, velocidadMotores);
}

void moverRetroceder() {
  digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);
  digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH);
  analogWrite(ENA, velocidadMotores);
  analogWrite(ENB, velocidadMotores);
}

void moverIzquierda() {
  digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);
  digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
  analogWrite(ENA, velocidadMotores);
  analogWrite(ENB, velocidadMotores);
}

void moverDerecha() {
  digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH);
  analogWrite(ENA, velocidadMotores);
  analogWrite(ENB, velocidadMotores);
}

void frenarMotores() {
  digitalWrite(IN1, LOW); digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW); digitalWrite(IN4, LOW);
  analogWrite(ENA, 0);
  analogWrite(ENB, 0);
}

void detenerServos() {
  cancelarAutoCabeza();
  servoBrazoIzq.write(90);
  servoCabeza.write(90);
  servoBrazoDer.write(90);
}

long medirDistancia() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duracion = pulseIn(ECHO_PIN, HIGH, 25000);
  if (duracion == 0) return 999;
  return duracion * 0.034 / 2;
}