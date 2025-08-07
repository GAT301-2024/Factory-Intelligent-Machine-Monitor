#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// --- Pin Definitions ---
#define DHTPIN 4
#define DHTTYPE DHT11
#define VIBRATION_PIN 16
#define RPM_PIN 17

// --- Network & API ---
const char* ssid = "V12";
const char* password = "Megado@67";
const char* serverUrl = "http://192.168.56.1:8000/log"; // Replace with your FastAPI server IP
const char* jwtToken = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJva2VsbG8gdmluY2VudCIsImV4cCI6MTc1NDMxNDA4N30.E5RHnrSFW7sWhX0_CbwilsvIdyBugcAw7pMppf2LaGc"; // Replace with your JWT token

// --- Sensor Objects ---
DHT dht(DHTPIN, DHTTYPE);

// --- RPM Measurement ---
volatile unsigned int pulseCount = 0;
unsigned long lastRPMCalc = 0;
float rpm = 0;

void IRAM_ATTR onPulse() {
  pulseCount++;
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  pinMode(VIBRATION_PIN, INPUT);
  pinMode(RPM_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(RPM_PIN), onPulse, FALLING);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected!");
}

void loop() {
  // --- Read Sensors ---
  float temp = dht.readTemperature();
  float humid = dht.readHumidity();
  int vib = digitalRead(VIBRATION_PIN);

  // --- Calculate RPM every second ---
  if (millis() - lastRPMCalc >= 1000) {
    rpm = pulseCount * 60; // 1 pulse per revolution
    pulseCount = 0;
    lastRPMCalc = millis();
  }

  // --- Only send if readings are valid ---
  if (!isnan(temp) && !isnan(humid)) {
    sendData(temp, humid, vib, rpm);
  } else {
    Serial.println("Sensor read error.");
  }

  delay(20000); // Send every 20 seconds (adjust as needed)
}

void sendData(float temp, float humid, int vib, float rpm) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", String("Bearer ") + jwtToken);

    StaticJsonDocument<256> doc;
    doc["temp"] = temp;
    doc["humid"] = humid;
    doc["vib"] = vib; // 0: Normal, 1: Alert
    doc["rpm"] = rpm;
    doc["timestamp"] = getISOTime();

    String payload;
    serializeJson(doc, payload);

    int httpResponseCode = http.POST(payload);
    Serial.print("POST ");
    Serial.print(serverUrl);
    Serial.print(" -> ");
    Serial.println(httpResponseCode);

    http.end();
  } else {
    Serial.println("WiFi not connected!");
  }
}

// --- Helper: Get ISO8601 Time String ---
String getISOTime() {
  time_t now;
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    return "";
  }
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);
  return String(buf);
}