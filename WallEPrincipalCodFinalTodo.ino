#include <Servo.h>

// Declaración de Servos (360° / Rotación Continua)
Servo servoBrazoIzq; // Pin 8 (Invertido)
Servo servoCabeza;   // Pin 9
Servo servoBrazoDer; // Pin 10

// Pines L298N (Motores DC)
const int ENA = 3;
const int IN1 = 4;
const int IN2 = 5;
const int IN3 = 6;
const int IN4 = 7;
const int ENB = 9; 

// Pines Sensor HC-SR04 Frontal
const int ECHO_PIN = 11;
const int TRIG_PIN = 12;

int velocidadMotores = 200;
unsigned long ultimoUltrasonico = 0;

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

    // --- CABEZA (PIN 9) ---
    case '1': servoCabeza.write(140); break;
    case '2': servoCabeza.write(40);  break;
    case '3': servoCabeza.write(90);  break;

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
    case 'A': ejecutarAutoCabeza(); break;

    // FRENAR TODO
    case 'X':
      frenarMotores();
      detenerServos();
      break;
  }
}

void ejecutarAutoCabeza() {
  servoCabeza.write(135);
  delay(5000);
  servoCabeza.write(45);
  delay(5000);
  servoCabeza.write(90);
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