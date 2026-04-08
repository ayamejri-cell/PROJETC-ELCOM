#!/usr/bin/env python3
"""
DOBOT HARD RESET COMPLET + TEST RELAIS
"""

from pydobot import Dobot
import RPi.GPIO as GPIO
import time
import sys

# ===============================
# CONFIGURATION
# ===============================
PORT = '/dev/ttyUSB0'
RELAY_PIN = 17   # GPIO utilisé
RELAY_ON = GPIO.HIGH   # ⚠️ à adapter si besoin
RELAY_OFF = GPIO.LOW

# ===============================
# INITIALISATION GPIO
# ===============================
def init_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RELAY_PIN, GPIO.OUT)

# ===============================
# TEST RELAIS (DEBUG HARDWARE)
# ===============================
def test_relay():
    print("\n🧪 TEST RELAIS (regarde la LED + DOBOT)")
    
    for i in range(3):
        print(f"Cycle {i+1} → ON")
        GPIO.output(RELAY_PIN, RELAY_ON)
        time.sleep(2)

        print(f"Cycle {i+1} → OFF")
        GPIO.output(RELAY_PIN, RELAY_OFF)
        time.sleep(2)

    print("✅ Test relais terminé\n")

# ===============================
# HARD RESET (VRAI)
# ===============================
def power_cycle_dobot():
    print("⚡ HARD RESET (coupure réelle)...")

    try:
        # OFF
        print("🔴 OFF (robot doit s’éteindre)")
        GPIO.output(RELAY_PIN, RELAY_OFF)
        time.sleep(4)

        # ON
        print("🟢 ON (robot doit redémarrer)")
        GPIO.output(RELAY_PIN, RELAY_ON)
        time.sleep(6)

        print("✅ Power cycle terminé")
        return True

    except Exception as e:
        print(f"❌ Erreur relais: {e}")
        return False

# ===============================
# RECOVERY DOBOT
# ===============================
def reset_and_recover():
    print("\n" + "="*50)
    print("🔧 DOBOT HARD RESET SYSTEM")
    print("="*50)

    # 1. Lire position
    try:
        dobot = Dobot(port=PORT, verbose=False)
        pose = dobot.pose()
        print(f"📍 Avant: X={pose[0]:.1f}, Y={pose[1]:.1f}, Z={pose[2]:.1f}")
        dobot.close()
    except:
        print("⚠️ Impossible de lire position")

    # 2. HARD RESET réel
    if not power_cycle_dobot():
        return False

    time.sleep(3)

    # 3. Reconnexion
    try:
        dobot = Dobot(port=PORT, verbose=False)
        print("✅ Reconnexion OK")

        # 4. Mouvement test
        print("📍 Mouvement test...")
        dobot.move_to(200, 0, 150, 0, wait=True)

        pose = dobot.pose()
        print(f"📍 Après: X={pose[0]:.1f}, Y={pose[1]:.1f}, Z={pose[2]:.1f}")

        print("🎉 Test terminé")
        return True

    except Exception as e:
        print(f"❌ Erreur DOBOT: {e}")
        return False

# ===============================
# MAIN
# ===============================
if __name__ == "__main__":

    init_gpio()

    print("\nChoix du mode :")
    print("1 → Test RELAIS seulement")
    print("2 → HARD RESET DOBOT complet")

    choice = input("👉 Ton choix: ")

    try:
        if choice == "1":
            test_relay()

        elif choice == "2":
            reset_and_recover()

        else:
            print("❌ Choix invalide")

    finally:
        GPIO.cleanup()
