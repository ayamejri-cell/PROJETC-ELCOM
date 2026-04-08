# -*- coding: utf-8 -*-

import math
import time

# ==============================
# 🔌 CONNEXION DOBOT
# ==============================

from DobotControl import DobotControl

dobot = DobotControl()

try:
    dobot.connect("/dev/ttyUSB0")  # ⚠️ adapter
    print("✅ DOBOT CONNECTÉ")
except Exception as e:
    print("❌ ERREUR CONNEXION DOBOT:", e)
    dobot = None

# ==============================
# 🔒 SAFE ZONE
# ==============================

SAFE_RADIUS = 250
MIN_RADIUS = 80
SAFE_Z_MIN = 50
SAFE_Z_MAX = 180

def is_safe_position(x, y, z):
    r = math.sqrt(x**2 + y**2)

    if r < MIN_RADIUS:
        return False, "Too close to center"

    if r > SAFE_RADIUS:
        return False, "Outside safe radius"

    if z < SAFE_Z_MIN or z > SAFE_Z_MAX:
        return False, "Z out of range"

    return True, None

# ==============================
# 🤖 MOVE SAFE
# ==============================

def safe_move_to(x, y, z):
    if dobot is None:
        print("❌ DOBOT NON CONNECTÉ")
        return

    safe, reason = is_safe_position(x, y, z)

    if not safe:
        print("❌ MOVE BLOCKED:", reason)
        return

    try:
        dobot.move_to(x, y, z)
        time.sleep(1)
        print("✅ MOVE OK")

    except Exception as e:
        print("❌ ERREUR MOUVEMENT:", e)

# ==============================
# 🧪 TEST
# ==============================

def test():
    print("\n🧪 TEST DOBOT")

    safe_move_to(150, 0, 120)
    safe_move_to(200, 50, 120)
    safe_move_to(300, 0, 120)

# ==============================
# 🚀 MAIN
# ==============================

if __name__ == "__main__":
    test()