// RaspDeck firmware — RP2040 Zero
// docs: https://github.com/itsmgxb24/RaspDeck-Software/Docs

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

#define LED_PIN 16

#define ROW0    0
#define ROW1    1
#define ROW2    2
#define COL0    3
#define COL1    6
#define COL2    7

#define MAX_DIN 12
#define MAX_CS  11
#define MAX_CLK 10

#define ENC_A   26
#define ENC_B   27
#define ENC_BTN 28

#define REG_NOOP        0x00
#define REG_DIGIT0      0x01  // rows 0-7 map to DIGIT0-DIGIT7
#define REG_DECODE      0x09
#define REG_INTENSITY   0x0A
#define REG_SCANLIMIT   0x0B
#define REG_SHUTDOWN    0x0C
#define REG_DISPLAYTEST 0x0F

const uint8_t ROWS[3]    = { ROW0, ROW1, ROW2 };
const uint8_t COLS[3]    = { COL0, COL1, COL2 };
bool          keyState[9] = { false };

volatile int  encDelta   = 0;
volatile bool encA_prev  = HIGH;
bool          encBtnPrev = HIGH;

// one byte per row, MSB is col 0
uint8_t framebuf[8] = { 0 };

Adafruit_NeoPixel led(1, LED_PIN, NEO_GRB + NEO_KHZ800);
uint8_t ledR = 255, ledG = 255, ledB = 255;  // current color
uint8_t ledBrightness = 255;                  // 0-255

void ledApply() {
  float scale = ledBrightness / 255.0f;
  led.setPixelColor(0, led.Color(
    (uint8_t)(ledR * scale),
    (uint8_t)(ledG * scale),
    (uint8_t)(ledB * scale)
  ));
  led.show();
}

void maxWrite(uint8_t reg, uint8_t data) {
  digitalWrite(MAX_CS, LOW);
  shiftOut(MAX_DIN, MAX_CLK, MSBFIRST, reg);
  shiftOut(MAX_DIN, MAX_CLK, MSBFIRST, data);
  digitalWrite(MAX_CS, HIGH);
}

void maxFlush() {
  for (uint8_t r = 0; r < 8; r++)
    maxWrite(REG_DIGIT0 + r, framebuf[r]);
}

void maxInit() {
  maxWrite(REG_DECODE,      0x00);
  maxWrite(REG_SCANLIMIT,   0x07);
  maxWrite(REG_INTENSITY,   0x04);
  maxWrite(REG_SHUTDOWN,    0x01);
  maxWrite(REG_DISPLAYTEST, 0x00);
}

void maxClear() {
  memset(framebuf, 0, 8);
  maxFlush();
}

// pixel n is 0-63, row-major from top-left
void setPixel(uint8_t n, bool on) {
  if (n > 63) return;
  uint8_t row = n / 8;
  uint8_t bit = 7 - (n % 8);
  if (on) framebuf[row] |=  (1 << bit);
  else    framebuf[row] &= ~(1 << bit);
}

void encoderISR() {
  bool a = digitalRead(ENC_A);
  bool b = digitalRead(ENC_B);
  if (a != encA_prev) {
    encDelta += (a != b) ? +1 : -1;
    encA_prev = a;
  }
}

void ltrim(String &s) {
  while (s.length() > 0 && s[0] == ' ')
    s.remove(0, 1);
}

void applyHumanReadablePixels(const String &list) {
  memset(framebuf, 0, 8);
  String rest = list;
  while (rest.length() > 0) {
    int comma = rest.indexOf(',');
    String token;
    if (comma < 0) {
      token = rest;
      rest  = "";
    } else {
      token = rest.substring(0, comma);
      rest  = rest.substring(comma + 1);
    }
    token.trim();
    if (token.length() > 0) {
      uint8_t n = (uint8_t)token.toInt();
      setPixel(n, true);
    }
  }
  maxFlush();
}

void handleCommand(const String &line) {
  int    sp   = line.indexOf(' ');
  String verb = (sp < 0) ? line : line.substring(0, sp);
  String rest = (sp < 0) ? ""   : line.substring(sp + 1);
  ltrim(rest);
  verb.toLowerCase();

  if (verb == "clear") {
    maxClear();

  } else if (verb == "bright") {
    int level = constrain(rest.toInt(), 0, 15);
    maxWrite(REG_INTENSITY, (uint8_t)level);

  } else if (verb == "pixel") {
    int space2 = rest.indexOf(' ');
    if (space2 > 0) {
      uint8_t n = (uint8_t)rest.substring(0, space2).toInt();
      bool    v = rest.substring(space2 + 1).toInt() != 0;
      setPixel(n, v);
      maxFlush();
    }

  } else if (verb == "pixels") {
    bool humanReadable = false;
    if (rest.startsWith("-h ") || rest.startsWith("--human-readable ")) {
      humanReadable = true;
      int flagEnd = rest.indexOf(' ');
      rest = rest.substring(flagEnd + 1);
      ltrim(rest);
    }
    if (humanReadable) {
      applyHumanReadablePixels(rest);
    } else {
      if (rest.length() >= 64) {
        for (uint8_t n = 0; n < 64; n++)
          setPixel(n, rest[n] == '1');
        maxFlush();
      }
    }

  } else if (verb == "led") {
    // led -c RRGGBB   set color as hex
    // led -b <0-100>  set brightness as percent
    if (rest.startsWith("-c ")) {
      String hex = rest.substring(3);
      hex.trim();
      if (hex.length() == 6) {
        ledR = (uint8_t)strtol(hex.substring(0, 2).c_str(), NULL, 16);
        ledG = (uint8_t)strtol(hex.substring(2, 4).c_str(), NULL, 16);
        ledB = (uint8_t)strtol(hex.substring(4, 6).c_str(), NULL, 16);
        ledApply();
      }
    } else if (rest.startsWith("-b ")) {
      int pct = constrain(rest.substring(3).toInt(), 0, 100);
      ledBrightness = (uint8_t)(pct / 100.0f * 255);
      ledApply();
    }

  } else if (verb == "ping") {
    Serial.println("pong");
  }
}

void setup() {
  Serial.begin(115200);

  // rows output high, cols input with pullups
  for (int r = 0; r < 3; r++) {
    pinMode(ROWS[r], OUTPUT);
    digitalWrite(ROWS[r], HIGH);
  }
  for (int c = 0; c < 3; c++)
    pinMode(COLS[c], INPUT_PULLUP);

  pinMode(MAX_DIN, OUTPUT);
  pinMode(MAX_CS,  OUTPUT);
  pinMode(MAX_CLK, OUTPUT);
  digitalWrite(MAX_CS, HIGH);
  maxInit();
  maxClear();

  led.begin();
  led.setBrightness(255);
  ledApply();

  // encoder needs pullups and interrupt on pin A
  pinMode(ENC_A,   INPUT_PULLUP);
  pinMode(ENC_B,   INPUT_PULLUP);
  pinMode(ENC_BTN, INPUT_PULLUP);
  encA_prev = digitalRead(ENC_A);
  attachInterrupt(digitalPinToInterrupt(ENC_A), encoderISR, CHANGE);
}

void loop() {
  // scan matrix row by row
  for (int r = 0; r < 3; r++) {
    digitalWrite(ROWS[r], LOW);
    delayMicroseconds(10);
    for (int c = 0; c < 3; c++) {
      int  idx     = r * 3 + c;
      bool pressed = (digitalRead(COLS[c]) == LOW);
      if (pressed != keyState[idx]) {
        keyState[idx] = pressed;
        Serial.print("BTN:");
        Serial.print(idx);
        Serial.print(":");
        Serial.println(pressed ? "P" : "R");
      }
    }
    digitalWrite(ROWS[r], HIGH);
  }

  // drain encoder ticks one at a time
  noInterrupts();
  int delta = encDelta;
  encDelta  = 0;
  interrupts();
  while (delta != 0) {
    Serial.println(delta > 0 ? "ENC:+1" : "ENC:-1");
    delta += (delta > 0) ? -1 : +1;
  }

  bool encBtnNow = (digitalRead(ENC_BTN) == LOW);
  if (encBtnNow != encBtnPrev) {
    encBtnPrev = encBtnNow;
    Serial.print("ENCBTN:");
    Serial.println(encBtnNow ? "P" : "R");
  }

  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) handleCommand(line);
  }

  delay(1);
}
