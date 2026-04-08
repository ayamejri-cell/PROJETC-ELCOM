"""

Dobot Magician Control Server - CORRECTED VERSION
Corrections basées sur le manuel Dobot (pages 14, 67, 82)
Objectif: Éliminer l'entrée dans les zones rouges (limited position)

Author: Your Name
Date: 2024
"""

from flask import Flask, request, jsonify
from pydobot import Dobot
import time
import threading
import platform
from queue import Queue, Empty
import math
import socket
import os
import sys
import json
from datetime import datetime


# ============================================================================
# INITIALIZATION
# ============================================================================

app = Flask(__name__)

# Global variables
dobot = None
is_executing = False
is_recording = False
recorded_trajectory = []
connection_error = None
stop_flag = False

# Configuration
PORT = '/dev/ttyUSB0'
SERVER_PORT = 5000
SERVER_HOST = '0.0.0.0'

# Movement parameters - BALANCED FOR RELIABILITY
MOVEMENT_TIMEOUT = 30
MAX_RETRIES = 3
DEFAULT_VELOCITY = 150
DEFAULT_ACCELERATION = 150
FAST_TRAJECTORY_VELOCITY = 200
FAST_TRAJECTORY_ACCELERATION = 200
MINIMUM_PAUSE_TIME = 0.1
GRIPPER_OPERATION_DELAY = 0.2
WAYPOINT_TRANSITION_DELAY = 0.1

# ============================================================================
# WORKSPACE LIMITS - CORRIGÉ SELON MANUEL DOBOT (Pages 14, 67, 82)
# ============================================================================
# Les valeurs originales causaient des zones rouges car trop larges
# Les nouvelles valeurs sont basées UNIQUEMENT sur le manuel

WORKSPACE_LIMITS = {
    'x': [-80, 80],      # CORRIGÉ: basé sur rayon max 80mm (manuel p.67, p.82)
    'y': [-80, 80],      # CORRIGÉ: basé sur rayon max 80mm (manuel p.67, p.82)
    'z': [0, 150],       # CORRIGÉ: Z min = surface (manuel p.67, p.82)
    'r': [-150, 150],    # CORRIGÉ: rotation outil ±150° (manuel p.14)
    'min_radius': 0,     # CORRIGÉ: pas de minimum spécifié dans manuel
    'max_radius': 80     # CORRIGÉ: 80mm max (manuel p.67, p.82)
}


# ============================================================================
# SIMPLE NETWORK FUNCTIONS (inchangé)
# ============================================================================

def get_ip_address():
    """Get the Raspberry Pi's IP address - SIMPLE VERSION"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        try:
            return socket.gethostbyname(socket.gethostname())
        except:
            return '127.0.0.1'


def get_all_ips_simple():
    """Get all IPs - simple version without netifaces"""
    ips = {
        'hostname': socket.gethostname(),
        'primary': get_ip_address()
    }
    
    try:
        import subprocess
        result = subprocess.run(['ip', 'addr', 'show'], 
                              capture_output=True, text=True, timeout=2)
        
        current_iface = None
        for line in result.stdout.split('\n'):
            line = line.strip()
            if ':' in line and line[0].isdigit():
                parts = line.split(':')
                if len(parts) > 1:
                    current_iface = parts[1].strip()
                    ips[current_iface] = []
            elif 'inet ' in line and current_iface:
                parts = line.split()
                if len(parts) > 1:
                    ip = parts[1].split('/')[0]
                    if ip != '127.0.0.1':
                        ips[current_iface].append(ip)
    except:
        pass
    
    return ips


def print_simple_network_info():
    """Print clean network information"""
    print("\n" + "="*60)
    print("🌐 NETWORK INFORMATION")
    print("="*60)
    
    all_ips = get_all_ips_simple()
    primary_ip = all_ips.get('primary', '127.0.0.1')
    
    print(f"\n🏷️  Hostname: {all_ips.get('hostname', 'Unknown')}")
    print(f"📍 Primary IP: {primary_ip}")
    
    print("\n🔌 Network Interfaces:")
    for key, value in all_ips.items():
        if key not in ['hostname', 'primary'] and isinstance(value, list):
            interface_type = "🔌 Ethernet" if key.startswith('eth') else "📡 WiFi" if key.startswith('wlan') else "🖥️  Interface"
            print(f"   {interface_type}: {key}")
            for ip in value:
                print(f"      IP: {ip}")
    
    print("\n" + "="*60)
    print("🚀 ACCESS POINTS")
    print("="*60)
    
    if 'eth0' in all_ips and all_ips['eth0']:
        print(f"\n🔌 ETHERNET (RECOMMENDED):")
        for ip in all_ips['eth0']:
            print(f"   IP: {ip}")
            print(f"   URL: http://{ip}:{SERVER_PORT}")
            print(f"   Test: curl http://{ip}:{SERVER_PORT}/status")
    
    if 'wlan0' in all_ips and all_ips['wlan0']:
        print(f"\n📡 WIFI:")
        for ip in all_ips['wlan0']:
            print(f"   IP: {ip}")
            print(f"   URL: http://{ip}:{SERVER_PORT}")
    
    print(f"\n💻 LOCAL ACCESS:")
    print(f"   URL: http://localhost:{SERVER_PORT}")
    print(f"   URL: http://127.0.0.1:{SERVER_PORT}")
    
    print("\n" + "="*60)


# ============================================================================
# NOUVELLE FONCTION - Détection zone rouge (basée manuel p.5, p.12)
# ============================================================================

def check_limited_position(dobot_instance):
    """
    Détecte si le robot est en position limite (zone rouge)
    Basé sur le manuel p.5 et p.12
    RETOURNE: True si en zone rouge, False sinon
    """
    try:
        pose = dobot_instance.pose()
        x, y, z, r = pose[0], pose[1], pose[2], pose[3]
        
        radius = math.sqrt(x**2 + y**2)
        
        # Conditions de zone rouge selon le manuel
        if radius > WORKSPACE_LIMITS['max_radius']:
            print(f"⚠️ ZONE ROUGE DÉTECTÉE: Rayon {radius:.1f}mm > {WORKSPACE_LIMITS['max_radius']}mm (manuel p.67)")
            return True
        if z > WORKSPACE_LIMITS['z'][1]:
            print(f"⚠️ ZONE ROUGE DÉTECTÉE: Z={z:.1f}mm > {WORKSPACE_LIMITS['z'][1]}mm (manuel p.67)")
            return True
        if z < WORKSPACE_LIMITS['z'][0]:
            print(f"⚠️ ZONE ROUGE DÉTECTÉE: Z={z:.1f}mm < {WORKSPACE_LIMITS['z'][0]}mm (manuel p.67)")
            return True
        if abs(r) > WORKSPACE_LIMITS['r'][1]:
            print(f"⚠️ ZONE ROUGE DÉTECTÉE: Rotation R={r:.1f}° > ±{WORKSPACE_LIMITS['r'][1]}° (manuel p.14)")
            return True
            
        return False
        
    except Exception as e:
        print(f"⚠️ Impossible de vérifier la position: {e}")
        return True  # Par sécurité, on considère zone rouge


# ============================================================================
# DOBOT FUNCTIONS - FONCTIONS CORRIGÉES
# ============================================================================

def init_dobot():
    """Initialize Dobot connection - VERSION CORRIGÉE avec vérification zone rouge"""
    global dobot, connection_error
    
    print("🔌 INITIALIZING DOBOT...")
    
    try:
        dobot = Dobot(port=PORT, verbose=True)
        pose = dobot.pose()
        print(f"✅ DOBOT CONNECTED")
        print(f"   Port: {PORT}")
        print(f"   Position: X={pose[0]:.1f}, Y={pose[1]:.1f}, Z={pose[2]:.1f}, R={pose[3]:.1f}")
        
        # NOUVEAU: Vérifier si la position actuelle est en zone rouge
        if check_limited_position(dobot):
            print("⚠️ Robot en zone rouge à l'initialisation!")
            print("   → Déplacement vers HOME sécurisé (50, 0, 100)")
            # Utiliser la position HOME sécurisée (rayon = 50mm < 80mm)
            try:
                dobot.move_to(50, 0, 100, 0, wait=True)
                time.sleep(0.5)
                print("   ✅ Déplacement sécurisé effectué")
            except Exception as home_error:
                print(f"   ⚠️ Impossible de déplacer le robot: {home_error}")
        
        try:
            dobot.speed(velocity=DEFAULT_VELOCITY, acceleration=DEFAULT_ACCELERATION)
            print(f"   Speed: {DEFAULT_VELOCITY}/{DEFAULT_ACCELERATION}")
        except:
            pass
        
        # Afficher les nouvelles limites
        print(f"   🔒 Limites de sécurité actives (manuel Dobot):")
        print(f"      Rayon max: {WORKSPACE_LIMITS['max_radius']}mm")
        print(f"      Z: {WORKSPACE_LIMITS['z'][0]}-{WORKSPACE_LIMITS['z'][1]}mm")
        print(f"      Rotation outil: ±{WORKSPACE_LIMITS['r'][1]}°")
        
        connection_error = None
        return True
        
    except Exception as e:
        connection_error = str(e)
        print(f"❌ DOBOT CONNECTION FAILED: {e}")
        return False


def validate_position_advanced(x, y, z, r):
    """
    Validate position - VERSION CORRIGÉE basée sur manuel
    NE PERMET PLUS LES POSITIONS HORS ZONE (élimine les zones rouges)
    """
    # Vérification X (basée sur rayon max)
    if abs(x) > WORKSPACE_LIMITS['max_radius']:
        return False, f"X={x:.1f} hors zone (max {WORKSPACE_LIMITS['max_radius']}mm - manuel p.67)"
    if abs(y) > WORKSPACE_LIMITS['max_radius']:
        return False, f"Y={y:.1f} hors zone (max {WORKSPACE_LIMITS['max_radius']}mm - manuel p.67)"
    
    # Vérification Z (manuel p.67)
    if not (WORKSPACE_LIMITS['z'][0] <= z <= WORKSPACE_LIMITS['z'][1]):
        return False, f"Z={z:.1f} hors zone (limite {WORKSPACE_LIMITS['z'][0]}-{WORKSPACE_LIMITS['z'][1]}mm - manuel p.67)"
    
    # Vérification R (manuel p.14)
    if not (WORKSPACE_LIMITS['r'][0] <= r <= WORKSPACE_LIMITS['r'][1]):
        return False, f"R={r:.1f}° hors zone (limite ±{WORKSPACE_LIMITS['r'][1]}° - manuel p.14)"
    
    # Vérification rayon (manuel p.67)
    radial_distance = math.sqrt(x**2 + y**2)
    if radial_distance > WORKSPACE_LIMITS['max_radius']:
        return False, f"Rayon {radial_distance:.1f}mm > {WORKSPACE_LIMITS['max_radius']}mm (manuel p.67)"
    
    return True, None


def move_with_timeout(dobot, x, y, z, r, timeout=15, retries=2):
    """Ultra-fast movement with aggressive timeout - INCHANGÉ"""
    for attempt in range(retries + 1):
        result_queue = Queue()
        
        def move_thread():
            try:
                dobot.move_to(x, y, z, r, wait=True)
                result_queue.put(('success', None))
            except Exception as e:
                result_queue.put(('error', str(e)))
        
        thread = threading.Thread(target=move_thread)
        thread.daemon = True
        thread.start()
        
        try:
            result, error = result_queue.get(timeout=timeout)
            if result == 'success':
                return True, None
            else:
                if attempt < retries:
                    time.sleep(0.1)
                    continue
                return False, error
        except Empty:
            if attempt < retries:
                time.sleep(0.1)
                continue
            return False, f"Timeout after {timeout}s"
    
    return False, "Max retries exceeded"


def safe_move_to(dobot, x, y, z, r, is_trajectory=False):
    """
    PRECISE movement - VERSION CORRIGÉE
    MAINETNANT BLOQUE LES MOUVEMENTS VERS ZONES ROUGES
    """
    
    print(f"📍 ATTEMPTING MOVE: ({x:.1f}, {y:.1f}, {z:.1f}, {r:.1f})")
    
    # ============================================================
    # ÉTAPE 1: VALIDATION OBLIGATOIRE (CORRIGÉ - NE PERMET PLUS LE PASSAGE)
    # ============================================================
    is_valid, error_msg = validate_position_advanced(x, y, z, r)
    
    # CORRECTION CRITIQUE: On ne "proceed anyway" plus!
    # Si la position est invalide, on bloque IMMÉDIATEMENT
    if not is_valid:
        print(f"❌ MOUVEMENT BLOQUÉ: {error_msg}")
        print(f"   → Position refusée pour éviter zone rouge (manuel p.5, p.12)")
        return False, error_msg
    
    # ============================================================
    # ÉTAPE 2: VÉRIFIER POSITION ACTUELLE (zone rouge)
    # ============================================================
    if check_limited_position(dobot):
        return False, "Robot actuellement en zone rouge - mouvement interdit (manuel p.5)"
    
    try:
        # Get current position
        pose = dobot.pose()
        curr_x, curr_y, curr_z, curr_r = pose[0], pose[1], pose[2], pose[3]
        
        print(f"📌 CURRENT POSITION: ({curr_x:.1f}, {curr_y:.1f}, {curr_z:.1f}, {curr_r:.1f})")
        
        total_dist = math.sqrt((x - curr_x)**2 + (y - curr_y)**2 + (z - curr_z)**2)
        print(f"📏 DISTANCE TO TARGET: {total_dist:.1f}mm")
        
        max_attempts = 3
        
        for attempt in range(max_attempts):
            print(f"🔧 MOVEMENT ATTEMPT {attempt + 1}/{max_attempts}")
            
            try:
                print("🚀 ATTEMPTING DIRECT MOVE...")
                dobot.move_to(x, y, z, r, wait=True)
                time.sleep(0.5)
                
                new_pose = dobot.pose()
                new_x, new_y, new_z, new_r = new_pose[0], new_pose[1], new_pose[2], new_pose[3]
                
                diff_x = abs(new_x - x)
                diff_y = abs(new_y - y)
                diff_z = abs(new_z - z)
                diff_r = abs(new_r - r)
                
                print(f"🎯 TARGET: ({x:.1f}, {y:.1f}, {z:.1f}, {r:.1f})")
                print(f"📍 ACTUAL: ({new_x:.1f}, {new_y:.1f}, {new_z:.1f}, {new_r:.1f})")
                
                tolerance = 5.0
                
                if diff_x <= tolerance and diff_y <= tolerance and diff_z <= tolerance and diff_r <= tolerance:
                    # NOUVEAU: Vérifier qu'on n'est pas entré en zone rouge après mouvement
                    if check_limited_position(dobot):
                        return False, "Mouvement réussi mais robot en zone rouge - arrêt sécurité"
                    print("✅ DIRECT MOVE SUCCESSFUL AND VERIFIED")
                    return True, None
                else:
                    print(f"⚠️ DIRECT MOVE COMPLETED BUT NOT ACCURATE (attempt {attempt + 1})")
                    if attempt < max_attempts - 1:
                        print("🔄 RETRYING WITH CORRECTIVE MOVE...")
                        try:
                            dobot.move_to(x, y, z, r, wait=True)
                            time.sleep(0.5)
                            
                            final_pose = dobot.pose()
                            final_diff_x = abs(final_pose[0] - x)
                            final_diff_y = abs(final_pose[1] - y)
                            final_diff_z = abs(final_pose[2] - z)
                            final_diff_r = abs(final_pose[3] - r)
                            
                            if (final_diff_x <= tolerance and final_diff_y <= tolerance and 
                                final_diff_z <= tolerance and final_diff_r <= tolerance):
                                
                                if check_limited_position(dobot):
                                    return False, "Mouvement réussi mais robot en zone rouge"
                                print("✅ CORRECTIVE MOVE SUCCESSFUL")
                                return True, None
                        except Exception as corrective_error:
                            print(f"❌ CORRECTIVE MOVE FAILED: {corrective_error}")
                    
            except Exception as direct_error:
                print(f"❌ DIRECT MOVE FAILED ON ATTEMPT {attempt + 1}: {direct_error}")
                
                if attempt < max_attempts - 1:
                    try:
                        print("🔧 ATTEMPTING RECOVERY STRATEGY...")
                        
                        safe_height = max(curr_z, z, 120)
                        print(f"⬆️  LIFTING to safe height: {safe_height}mm")
                        dobot.move_to(curr_x, curr_y, safe_height, curr_r, wait=True)
                        time.sleep(0.3)
                        
                        print(f"➡️  HORIZONTAL MOVE to target X,Y: ({x}, {y})")
                        dobot.move_to(x, y, safe_height, r, wait=True)
                        time.sleep(0.3)
                        
                        print(f"⬇️  DESCENDING to target Z: {z}mm")
                        dobot.move_to(x, y, z, r, wait=True)
                        time.sleep(0.5)
                        
                        recovery_pose = dobot.pose()
                        rec_diff_x = abs(recovery_pose[0] - x)
                        rec_diff_y = abs(recovery_pose[1] - y)
                        rec_diff_z = abs(recovery_pose[2] - z)
                        rec_diff_r = abs(recovery_pose[3] - r)
                        
                        if (rec_diff_x <= tolerance and rec_diff_y <= tolerance and 
                            rec_diff_z <= tolerance and rec_diff_r <= tolerance):
                            
                            if check_limited_position(dobot):
                                return False, "Récupération réussie mais robot en zone rouge"
                            print("✅ RECOVERY MOVE SUCCESSFUL")
                            return True, None
                        else:
                            print(f"⚠️ RECOVERY MOVE COMPLETED BUT NOT ACCURATE")
                            
                    except Exception as recovery_error:
                        print(f"❌ RECOVERY FAILED: {recovery_error}")
        
        error_message = f"Movement failed after {max_attempts} attempts"
        print(f"❌ ALL MOVEMENT ATTEMPTS FAILED: {error_message}")
        return False, error_message
                
    except Exception as e:
        error_message = f"Movement system error: {str(e)}"
        print(f"❌ MOVEMENT SYSTEM ERROR: {error_message}")
        return False, error_message


def execute_trajectory_async(trajectory):
    """Execute trajectory with PRECISE movement validation - VERSION CORRIGÉE"""
    global is_executing, stop_flag
    is_executing = True
    stop_flag = False
    
    try:
        original_velocity = getattr(dobot, '_velocity', DEFAULT_VELOCITY)
        original_acceleration = getattr(dobot, '_acceleration', DEFAULT_ACCELERATION)
        
        try:
            dobot.speed(velocity=FAST_TRAJECTORY_VELOCITY, acceleration=FAST_TRAJECTORY_ACCELERATION)
            print(f"🔥 ULTRA-HIGH SPEED MODE: {FAST_TRAJECTORY_VELOCITY}/{FAST_TRAJECTORY_ACCELERATION}")
        except:
            try:
                dobot.speed(velocity=255, acceleration=255)
                print(f"🔥 MAXIMUM HARDWARE SPEED: 255/255")
            except:
                pass
        
        print(f"🎯 Executing {len(trajectory)} steps with PRECISE positioning")
        
        execution_log = []
        
        for i, step in enumerate(trajectory):
            if stop_flag:
                execution_log.append(f"🛑 Execution stopped at step {i+1}")
                break
            
            step_log = f"Step {i+1}: "
            
            if not isinstance(step, dict):
                step_log += f"❌ Invalid step format: {type(step)}"
                print(step_log)
                execution_log.append(step_log)
                continue
            
            if 'gripper' in step:
                gripper_cmd = step['gripper']
                if isinstance(gripper_cmd, str):
                    gripper_lower = gripper_cmd.lower().strip()
                    if gripper_lower in ['close', 'closed', '1', 'true']:
                        dobot.grip(True)
                        step_log += "✋ Gripper CLOSED "
                    elif gripper_lower in ['open', 'opened', '0', 'false']:
                        dobot.grip(False)
                        step_log += "👐 Gripper OPENED "
                    else:
                        step_log += f"❓ Unknown gripper command: '{gripper_cmd}' "
                else:
                    step_log += f"❌ Invalid gripper command type: {type(gripper_cmd)} "
                
                time.sleep(GRIPPER_OPERATION_DELAY)
            
            movement_fields = ['x', 'y', 'z', 'r']
            has_movement = any(field in step for field in movement_fields)
            
            if has_movement:
                try:
                    # CORRECTION: Utiliser des valeurs par défaut SÉCURISÉES
                    x = float(step.get('x', 50))   # Changé: 200 → 50 (rayon 50mm < 80mm)
                    y = float(step.get('y', 0))
                    z = float(step.get('z', 100))  # Changé: 150 → 100 (dans zone sécurisée)
                    r = float(step.get('r', 0))
                    
                    step_log += f"📍 Moving to ({x:.1f}, {y:.1f}, {z:.1f}, {r:.1f}) "
                    
                    success, error = safe_move_to(dobot, x, y, z, r, is_trajectory=True)
                    if success:
                        step_log += "✅ SUCCESS"
                    else:
                        step_log += f"❌ FAILED: {error}"
                        print(step_log)
                        execution_log.append(step_log)
                        print(f"⚠️  Arrêt de la trajectoire à l'étape {i+1} pour éviter zone rouge")
                        break  # CORRECTION: Arrêter la trajectoire au lieu de continuer
                        
                except (ValueError, TypeError) as e:
                    step_log += f"❌ COORDINATE ERROR: {e}"
                    print(step_log)
                    execution_log.append(step_log)
                    break
            
            if 'pause' in step:
                try:
                    pause_time = float(step['pause'])
                    if pause_time > 0:
                        actual_pause = max(MINIMUM_PAUSE_TIME, pause_time * 0.3)
                        step_log += f"⏱️ Pausing {actual_pause:.2f}s "
                        time.sleep(actual_pause)
                except (ValueError, TypeError):
                    step_log += "❌ Invalid pause value "
            
            print(step_log)
            execution_log.append(step_log)
        
        print("✅ PRECISE Trajectory execution completed")
        print(f"📝 Execution Summary: {len(execution_log)} steps processed")
        
    except Exception as e:
        print(f"❌ Critical error in trajectory execution: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            dobot.speed(velocity=original_velocity, acceleration=original_acceleration)
            print(f"🔧 Restored original speed: {original_velocity}/{original_acceleration}")
        except:
            pass
        is_executing = False


# ============================================================================
# FLASK ENDPOINTS - VERSION CORRIGÉE (HOME position)
# ============================================================================

@app.route('/')
def index():
    """Home page"""
    ip = get_ip_address()
    return jsonify({
        'server': 'Dobot Control Server - CORRECTED VERSION',
        'version': '2.0',
        'ip': ip,
        'port': SERVER_PORT,
        'access': f'http://{ip}:{SERVER_PORT}',
        'endpoints': ['/', '/status', '/network', '/manual', '/execute', '/stop'],
        'safety_limits': {
            'max_radius_mm': WORKSPACE_LIMITS['max_radius'],
            'z_range_mm': WORKSPACE_LIMITS['z'],
            'r_range_deg': WORKSPACE_LIMITS['r'],
            'based_on': 'Dobot Manual pages 14, 67, 82'
        }
    })


@app.route('/status')
def status():
    """Status endpoint"""
    position = None
    in_red_zone = False
    
    if dobot:
        try:
            pose = dobot.pose()
            position = {'x': pose[0], 'y': pose[1], 'z': pose[2], 'r': pose[3]}
            in_red_zone = check_limited_position(dobot)
        except:
            pass
    
    return jsonify({
        'dobot_connected': dobot is not None,
        'dobot_error': connection_error,
        'position': position,
        'in_red_zone': in_red_zone,  # NOUVEAU: indique si robot en zone rouge
        'executing': is_executing,
        'recording': is_recording,
        'server_ip': get_ip_address(),
        'server_port': SERVER_PORT,
        'safety_active': True
    })


@app.route('/network')
def network():
    """Network info"""
    all_ips = get_all_ips_simple()
    return jsonify({
        'hostname': all_ips.get('hostname'),
        'primary_ip': all_ips.get('primary'),
        'interfaces': {k: v for k, v in all_ips.items() 
                      if k not in ['hostname', 'primary'] and isinstance(v, list)},
        'server_urls': [
            f'http://{all_ips.get("primary")}:{SERVER_PORT}',
            'http://localhost:5000'
        ]
    })


@app.route('/manual', methods=['POST'])
def manual():
    """Manual control - VERSION CORRIGÉE (HOME position sécurisée)"""
    if not dobot:
        return jsonify({'error': 'Dobot not connected'}), 503
    
    data = request.json
    if not data:
        return jsonify({'error': 'No data'}), 400
    
    command = data.get('command')
    params = data.get('params', {})
    
    if command == 'home':
        # CORRECTION: Position HOME sécurisée (rayon = 50mm < 80mm)
        # Ancienne position (200, 0, 150) était HORS ZONE (rayon 200 > 80)
        success, error = safe_move_to(dobot, 50, 0, 100, 0)
        if success:
            return jsonify({'success': True, 'message': 'Moved to safe home position (50, 0, 100)'})
        else:
            return jsonify({'error': error}), 500
    
    elif command == 'move':
        x = float(data.get('x', 50))     # Changé: valeur par défaut sécurisée
        y = float(data.get('y', 0))
        z = float(data.get('z', 100))    # Changé: valeur par défaut sécurisée
        r = float(data.get('r', 0))
        
        success, error = safe_move_to(dobot, x, y, z, r)
        if success:
            return jsonify({'success': True, 'message': f'Moved to {x},{y},{z},{r}'})
        else:
            return jsonify({'error': error}), 500
    
    elif command == 'gripper':
        state = data.get('state', 'open')
        dobot.grip(state.lower() == 'close')
        time.sleep(0.5)
        return jsonify({'success': True, 'message': f'Gripper {state}'})
    
    elif command == 'get_position':
        try:
            pose = dobot.pose()
            return jsonify({
                'success': True,
                'position': {
                    'x': round(pose[0], 2),
                    'y': round(pose[1], 2),
                    'z': round(pose[2], 2),
                    'r': round(pose[3], 2)
                },
                'in_red_zone': check_limited_position(dobot)  # NOUVEAU
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif command == 'pause':
        seconds = float(params.get('seconds', 1))
        time.sleep(seconds)
        return jsonify({'success': True, 'message': f'Paused for {seconds} seconds'})
    
    elif command == 'gripper_rotate':
        angle = float(params.get('angle', 0))
        try:
            current_pose = dobot.pose()
            new_r = current_pose[3] + angle
            # CORRECTION: Limite selon manuel p.14 (±150°)
            new_r = max(WORKSPACE_LIMITS['r'][0], min(WORKSPACE_LIMITS['r'][1], new_r))
            success, error = safe_move_to(dobot, current_pose[0], current_pose[1], current_pose[2], new_r)
            if success:
                return jsonify({'success': True, 'message': f'Gripper rotated by {angle} degrees to {new_r} degrees'})
            else:
                return jsonify({'error': error}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif command == 'move_relative':
        dx = float(params.get('dx', 0))
        dy = float(params.get('dy', 0))
        dz = float(params.get('dz', 0))
        dr = float(params.get('dr', 0))
        
        try:
            current_pose = dobot.pose()
            new_x = current_pose[0] + dx
            new_y = current_pose[1] + dy
            new_z = current_pose[2] + dz
            new_r = current_pose[3] + dr
            
            success, error = safe_move_to(dobot, new_x, new_y, new_z, new_r)
            if success:
                return jsonify({'success': True, 'message': f'Moved by ({dx},{dy},{dz},{dr}) to ({new_x:.1f},{new_y:.1f},{new_z:.1f},{new_r:.1f})'})
            else:
                return jsonify({'error': error}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': f'Unknown command: {command}'}), 400


@app.route('/execute', methods=['POST'])
def execute():
    """Execute trajectory with speed optimization - Enhanced for scenario support"""
    global is_executing
    
    if is_executing:
        return jsonify({'error': 'Already executing'}), 400
    
    if not dobot:
        return jsonify({'error': 'Dobot not connected'}), 503
    
    data = request.json
    if not data or 'trajectory' not in data:
        return jsonify({'error': 'No trajectory'}), 400
    
    trajectory = data['trajectory']
    
    client_ip = request.environ.get('REMOTE_ADDR', 'unknown')
    user_agent = request.headers.get('User-Agent', 'unknown')
    
    print(f"🎯 SCENARIO EXECUTION REQUEST")
    print(f"   Client IP: {client_ip}")
    print(f"   User Agent: {user_agent}")
    print(f"   Trajectory Steps: {len(trajectory)}")
    
    if not isinstance(trajectory, list):
        return jsonify({'error': 'Trajectory must be a list of steps'}), 400
    
    print("   First 3 steps:")
    for i, step in enumerate(trajectory[:3]):
        if isinstance(step, dict):
            coords = []
            if 'x' in step: coords.append(f"X={step['x']}")
            if 'y' in step: coords.append(f"Y={step['y']}")
            if 'z' in step: coords.append(f"Z={step['z']}")
            if 'r' in step: coords.append(f"R={step['r']}")
            if 'gripper' in step: coords.append(f"Gripper={step['gripper']}")
            if 'pause' in step: coords.append(f"Pause={step['pause']}s")
            print(f"     Step {i+1}: {', '.join(coords) if coords else 'Empty step'}")
        else:
            print(f"     Step {i+1}: Invalid format ({type(step)})")
    
    if len(trajectory) > 3:
        print(f"     ... and {len(trajectory) - 3} more steps")
    
    thread = threading.Thread(target=execute_trajectory_async, args=(trajectory,))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'message': f'Scenario trajectory execution started: {len(trajectory)} steps',
        'steps': len(trajectory),
        'client_info': {
            'ip': client_ip,
            'user_agent': user_agent
        },
        'speed_profile': {
            'velocity': FAST_TRAJECTORY_VELOCITY,
            'acceleration': FAST_TRAJECTORY_ACCELERATION,
            'mode': 'SCENARIO_HIGH_SPEED'
        },
        'execution_id': f"exec_{int(time.time())}"
    })


@app.route('/scenario/execute', methods=['POST'])
def execute_scenario():
    """Dedicated endpoint for scenario execution with enhanced logging"""
    global is_executing

    if is_executing:
        return jsonify({'error': 'Already executing'}), 400

    if not dobot:
        return jsonify({'error': 'Dobot not connected'}), 503

    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    trajectory = data.get('trajectory') or data.get('trajectory_data')
    scenario_name = data.get('scenario_name', 'Unnamed Scenario')
    scenario_id = data.get('scenario_id', 'unknown')

    if not trajectory:
        return jsonify({'error': 'No trajectory data provided'}), 400

    client_ip = request.environ.get('REMOTE_ADDR', 'unknown')
    user_agent = request.headers.get('User-Agent', 'unknown')

    print(f"🎯 SCENARIO EXECUTION: {scenario_name} (ID: {scenario_id})")
    print(f"   Client IP: {client_ip}")
    print(f"   User Agent: {user_agent}")
    print(f"   Trajectory Steps: {len(trajectory)}")

    if not isinstance(trajectory, list):
        return jsonify({'error': 'Trajectory must be a list of steps'}), 400

    print("   First 3 steps:")
    for i, step in enumerate(trajectory[:3]):
        if isinstance(step, dict):
            coords = []
            if 'x' in step: coords.append(f"X={step['x']}")
            if 'y' in step: coords.append(f"Y={step['y']}")
            if 'z' in step: coords.append(f"Z={step['z']}")
            if 'r' in step: coords.append(f"R={step['r']}")
            if 'gripper' in step: coords.append(f"Gripper={step['gripper']}")
            if 'pause' in step: coords.append(f"Pause={step['pause']}s")
            print(f"     Step {i+1}: {', '.join(coords) if coords else 'Empty step'}")
        else:
            print(f"     Step {i+1}: Invalid format ({type(step)})")

    if len(trajectory) > 3:
        print(f"     ... and {len(trajectory) - 3} more steps")

    thread = threading.Thread(target=execute_trajectory_async, args=(trajectory,))
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'message': f'Scenario "{scenario_name}" execution started successfully',
        'scenario_name': scenario_name,
        'scenario_id': scenario_id,
        'steps': len(trajectory),
        'client_info': {
            'ip': client_ip,
            'user_agent': user_agent
        },
        'speed_profile': {
            'velocity': FAST_TRAJECTORY_VELOCITY,
            'acceleration': FAST_TRAJECTORY_ACCELERATION,
            'mode': 'SCENARIO_ULTRA_HIGH_SPEED'
        },
        'execution_id': f"scenario_exec_{int(time.time())}"
    })


@app.route('/record/start', methods=['POST'])
def start_record():
    """Start recording"""
    global is_recording, recorded_trajectory
    is_recording = True
    recorded_trajectory = []
    return jsonify({'success': True, 'message': 'Recording started'})


@app.route('/record/stop', methods=['POST'])
def stop_record():
    """Stop recording"""
    global is_recording, recorded_trajectory
    is_recording = False
    trajectory = recorded_trajectory.copy()
    recorded_trajectory = []
    return jsonify({
        'success': True,
        'message': f'Recorded {len(trajectory)} steps',
        'trajectory': trajectory
    })


@app.route('/stop', methods=['POST'])
def stop():
    """Emergency stop"""
    global stop_flag
    stop_flag = True
    return jsonify({'success': True, 'message': 'Stop command sent'})


@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'dobot': 'connected' if dobot else 'disconnected',
        'timestamp': datetime.now().isoformat()
    })


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    os.system('clear')
    
    print("\n" + "="*60)
    print("🤖 DOBOT MAGICIAN CONTROL SERVER - CORRECTED VERSION")
    print("="*60)
    print("\n📖 CORRECTIONS APPLIQUÉES (basées manuel Dobot):")
    print("   1. Rayon max: 340mm → 80mm (manuel p.67, p.82)")
    print("   2. Z min: -100mm → 0mm (manuel p.67, p.82)")
    print("   3. Rotation outil: ±180° → ±150° (manuel p.14)")
    print("   4. HOME position: (200,0,150) → (50,0,100) (rayon 50mm < 80mm)")
    print("   5. Validation OBLIGATOIRE des positions avant mouvement")
    print("   6. Détection zone rouge avant/après chaque mouvement")
    print("="*60)
    
    print_simple_network_info()
    
    init_dobot()
    
    print("\n" + "="*60)
    print("🚀 STARTING SERVER")
    print("="*60)
    print(f"   Server will start on port {SERVER_PORT}")
    print("   Press Ctrl+C to stop\n")
    
    try:
        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        if dobot:
            print("\n🔧 Returning to safe home position...")
            try:
                # Utiliser la position HOME sécurisée (50, 0, 100)
                safe_move_to(dobot, 50, 0, 100, 0)
                print("✅ Cleanup done")
            except:
                print("⚠️ Cleanup failed")
        print("\n👋 Goodbye!\n")