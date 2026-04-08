#!/usr/bin/env python3
"""
DOBOT HARD RESET - Reset matériel réel via relais GPIO
"""

from pydobot import Dobot
import time
import sys
import RPi.GPIO as GPIO

PORT = '/dev/ttyUSB0'
RELAY_PIN = 17  # GPIO17

# ===============================
# 🔌 HARD RESET (VRAI)
# ===============================
def power_cycle_dobot():
    """Coupe réellement l'alimentation du DOBOT"""
    
    print("⚡ HARD RESET (coupure alimentation)...")
    
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RELAY_PIN, GPIO.OUT)

    try:
        # ⚠️ Adapter selon ton relais (HIGH/LOW)
        
        print("🔴 OFF (coupure)")
        GPIO.output(RELAY_PIN, GPIO.LOW)
        time.sleep(3)

        print("🟢 ON (redémarrage)")
        GPIO.output(RELAY_PIN, GPIO.HIGH)
        time.sleep(5)

        print("✅ Alimentation restaurée")
        return True

    except Exception as e:
        print(f"❌ Erreur relais: {e}")
        return False

    finally:
        GPIO.cleanup()


# ===============================
# 🤖 RECOVERY COMPLET
# ===============================
def force_unlock_with_hard_reset():
    
    print("\n" + "="*50)
    print("🔧 DOBOT HARD RESET RECOVERY (REAL)")
    print("="*50)
    
    # 1. Lire position avant
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

    time.sleep(2)

    # 3. Reconnexion
    try:
        dobot = Dobot(port=PORT, verbose=False)
        print("✅ Reconnexion OK")

        # 4. Mouvement de recovery
        print("📍 Move vers position safe...")
        dobot.move_to(200, 0, 150, 0, wait=True)
        time.sleep(1)

        pose = dobot.pose()
        print(f"📍 Après: X={pose[0]:.1f}, Y={pose[1]:.1f}, Z={pose[2]:.1f}")

        if abs(pose[0] - 200) < 50:
            print("🎉 Robot débloqué")
            return True
        else:
            print("⚠️ Toujours bloqué")
            return False

    except Exception as e:
        print(f"❌ Erreur reconnexion: {e}")
        return False


# ===============================
# 🚀 MAIN
# ===============================
if __name__ == "__main__":
    
    if force_unlock_with_hard_reset():
        sys.exit(0)
    else:
        print("\n❌ Intervention manuelle nécessaire")
        sys.exit(1)