"""

Dobot Magician Control Server - PREVENTION TOTALE DES ZONES ROUGES
Avec correction automatique des positions avant mouvement

Philosophie: Ne JAMAIS entrer en zone rouge (correction à la base)
Le robot exécute TOUS les mouvements (corrigés automatiquement)

Author: Your Name
Date: 2024
"""

from flask import Flask, request, jsonify
from pydobot import Dobot
import time
import threading
import math
import socket
import os
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

# Movement parameters
MOVEMENT_TIMEOUT = 30
MAX_RETRIES = 3
DEFAULT_VELOCITY = 150
DEFAULT_ACCELERATION = 150
FAST_TRAJECTORY_VELOCITY = 200
FAST_TRAJECTORY_ACCELERATION = 200
MINIMUM_PAUSE_TIME = 0.1
GRIPPER_OPERATION_DELAY = 0.2

# ============================================================================
# WORKSPACE LIMITS - BASÉ SUR MANUEL DOBOT (Pages 14, 67, 82)
# ============================================================================

WORKSPACE_LIMITS = {
    'x': [-80, 80],
    'y': [-80, 80],
    'z': [0, 150],
    'r': [-150, 150],
    'max_radius': 80
}

# Position HOME sécurisée (rayon = 50mm < 80mm)
HOME_POSITION = {'x': 50, 'y': 0, 'z': 100, 'r': 0}


# ============================================================================
# FONCTION CRITIQUE : CORRECTION AUTOMATIQUE DES POSITIONS
# ============================================================================

def validate_and_correct_position(x, y, z, r):
    """
    Valide ET CORRIGE automatiquement les positions dangereuses.
    Le robot n'entre JAMAIS en zone rouge car on corrige avant.
    
    Retourne: (x_corrige, y_corrige, z_corrige, r_corrige, a_ete_corrige)
    """
    
    x_c, y_c, z_c, r_c = x, y, z, r
    a_ete_corrige = False
    corrections = []
    
    # 1. CORRECTION DU RAYON (trop loin = ramené à la limite)
    radius = math.sqrt(x_c**2 + y_c**2)
    if radius > WORKSPACE_LIMITS['max_radius']:
        ratio = WORKSPACE_LIMITS['max_radius'] / radius
        x_c = x_c * ratio
        y_c = y_c * ratio
        corrections.append(f"Rayon {radius:.1f}mm → {WORKSPACE_LIMITS['max_radius']}mm")
        a_ete_corrige = True
    
    # 2. CORRECTION Z (trop bas = remonté à 0)
    if z_c < WORKSPACE_LIMITS['z'][0]:
        corrections.append(f"Z {z_c:.1f}mm → {WORKSPACE_LIMITS['z'][0]}mm")
        z_c = WORKSPACE_LIMITS['z'][0]
        a_ete_corrige = True
    
    # 3. CORRECTION Z (trop haut = descendu à max)
    if z_c > WORKSPACE_LIMITS['z'][1]:
        corrections.append(f"Z {z_c:.1f}mm → {WORKSPACE_LIMITS['z'][1]}mm")
        z_c = WORKSPACE_LIMITS['z'][1]
        a_ete_corrige = True
    
    # 4. CORRECTION R (rotation outil - manuel p.14)
    if r_c < WORKSPACE_LIMITS['r'][0]:
        corrections.append(f"R {r_c:.1f}° → {WORKSPACE_LIMITS['r'][0]}°")
        r_c = WORKSPACE_LIMITS['r'][0]
        a_ete_corrige = True
    if r_c > WORKSPACE_LIMITS['r'][1]:
        corrections.append(f"R {r_c:.1f}° → {WORKSPACE_LIMITS['r'][1]}°")
        r_c = WORKSPACE_LIMITS['r'][1]
        a_ete_corrige = True
    
    # 5. CORRECTION X/Y individuelles (sécurité supplémentaire)
    if x_c < WORKSPACE_LIMITS['x'][0]:
        corrections.append(f"X {x_c:.1f}mm → {WORKSPACE_LIMITS['x'][0]}mm")
        x_c = WORKSPACE_LIMITS['x'][0]
        a_ete_corrige = True
    if x_c > WORKSPACE_LIMITS['x'][1]:
        corrections.append(f"X {x_c:.1f}mm → {WORKSPACE_LIMITS['x'][1]}mm")
        x_c = WORKSPACE_LIMITS['x'][1]
        a_ete_corrige = True
    if y_c < WORKSPACE_LIMITS['y'][0]:
        corrections.append(f"Y {y_c:.1f}mm → {WORKSPACE_LIMITS['y'][0]}mm")
        y_c = WORKSPACE_LIMITS['y'][0]
        a_ete_corrige = True
    if y_c > WORKSPACE_LIMITS['y'][1]:
        corrections.append(f"Y {y_c:.1f}mm → {WORKSPACE_LIMITS['y'][1]}mm")
        y_c = WORKSPACE_LIMITS['y'][1]
        a_ete_corrige = True
    
    if a_ete_corrige:
        print(f"⚠️ CORRECTION AUTO: {', '.join(corrections)}")
    
    return x_c, y_c, z_c, r_c, a_ete_corrige


def check_if_position_safe(x, y, z, r):
    """
    Vérifie si une position est dans la zone sûre (sans correction)
    Retourne: (est_safe, message, rayon)
    """
    radius = math.sqrt(x**2 + y**2)
    
    if radius > WORKSPACE_LIMITS['max_radius']:
        return False, f"Rayon {radius:.1f}mm > {WORKSPACE_LIMITS['max_radius']}mm", radius
    if z < WORKSPACE_LIMITS['z'][0]:
        return False, f"Z {z:.1f}mm < {WORKSPACE_LIMITS['z'][0]}mm", radius
    if z > WORKSPACE_LIMITS['z'][1]:
        return False, f"Z {z:.1f}mm > {WORKSPACE_LIMITS['z'][1]}mm", radius
    if abs(r) > WORKSPACE_LIMITS['r'][1]:
        return False, f"R {r:.1f}° > ±{WORKSPACE_LIMITS['r'][1]}°", radius
    
    return True, "OK", radius


# ============================================================================
# NETWORK FUNCTIONS
# ============================================================================

def get_ip_address():
    """Get the Raspberry Pi's IP address"""
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


def print_network_info():
    """Print network information"""
    print("\n" + "="*60)
    print("🌐 NETWORK INFORMATION")
    print("="*60)
    
    ip = get_ip_address()
    print(f"\n📍 IP Address: {ip}")
    print(f"🌐 Server URL: http://{ip}:{SERVER_PORT}")
    print(f"💻 Local URL: http://localhost:{SERVER_PORT}")
    print("\n" + "="*60)


# ============================================================================
# DOBOT FUNCTIONS - AVEC CORRECTION AUTOMATIQUE
# ============================================================================

def init_dobot():
    """Initialize Dobot connection"""
    global dobot, connection_error
    
    print("🔌 INITIALIZING DOBOT...")
    
    try:
        dobot = Dobot(port=PORT, verbose=False)
        pose = dobot.pose()
        
        print(f"✅ DOBOT CONNECTED")
        print(f"   Port: {PORT}")
        print(f"   Position: X={pose[0]:.1f}, Y={pose[1]:.1f}, Z={pose[2]:.1f}, R={pose[3]:.1f}")
        
        # Vérifier si la position actuelle est sûre
        radius = math.sqrt(pose[0]**2 + pose[1]**2)
        if radius > WORKSPACE_LIMITS['max_radius'] or pose[2] < 0:
            print(f"⚠️ Robot en position dangereuse! Déplacement vers HOME...")
            dobot.move_to(HOME_POSITION['x'], HOME_POSITION['y'], 
                         HOME_POSITION['z'], HOME_POSITION['r'], wait=True)
            time.sleep(0.5)
            print(f"   ✅ Déplacement HOME effectué")
        
        try:
            dobot.speed(velocity=DEFAULT_VELOCITY, acceleration=DEFAULT_ACCELERATION)
            print(f"   Speed: {DEFAULT_VELOCITY}/{DEFAULT_ACCELERATION}")
        except:
            pass
        
        print(f"\n🔒 LIMITES DE SÉCURITÉ (manuel Dobot):")
        print(f"   Rayon max: {WORKSPACE_LIMITS['max_radius']}mm")
        print(f"   Z: {WORKSPACE_LIMITS['z'][0]}-{WORKSPACE_LIMITS['z'][1]}mm")
        print(f"   Rotation outil: ±{WORKSPACE_LIMITS['r'][1]}°")
        print(f"\n🔄 CORRECTION AUTOMATIQUE: ACTIVÉE")
        print(f"   → Toutes les positions dangereuses sont corrigées automatiquement")
        print(f"   → Le robot n'entre JAMAIS en zone rouge")
        
        connection_error = None
        return True
        
    except Exception as e:
        connection_error = str(e)
        print(f"❌ DOBOT CONNECTION FAILED: {e}")
        return False


def safe_move_to(dobot, x, y, z, r, is_trajectory=False):
    """
    Mouvement avec CORRECTION AUTOMATIQUE à la base.
    Le robot n'entre JAMAIS en zone rouge car on corrige avant.
    """
    
    # ÉTAPE 1: Corriger la position demandée (CRITIQUE)
    x_corrige, y_corrige, z_corrige, r_corrige, a_ete_corrige = validate_and_correct_position(x, y, z, r)
    
    # Afficher la correction si nécessaire
    if a_ete_corrige:
        print(f"📍 Position originale: ({x:.1f}, {y:.1f}, {z:.1f}, {r:.1f})")
        print(f"📍 Position corrigée: ({x_corrige:.1f}, {y_corrige:.1f}, {z_corrige:.1f}, {r_corrige:.1f})")
    
    # ÉTAPE 2: Vérification de sécurité supplémentaire (juste pour log)
    est_safe, message, radius = check_if_position_safe(x_corrige, y_corrige, z_corrige, r_corrige)
    if not est_safe:
        # Ce cas ne devrait jamais arriver car on a corrigé
        print(f"⚠️ ATTENTION: Position encore dangereuse après correction: {message}")
        return False, message
    
    # ÉTAPE 3: Vérifier que le robot n'est pas déjà dans une position dangereuse
    try:
        pose = dobot.pose()
        radius_actuel = math.sqrt(pose[0]**2 + pose[1]**2)
        if radius_actuel > WORKSPACE_LIMITS['max_radius'] or pose[2] < 0:
            print("🚨 Robot en position dangereuse! Récupération forcée vers HOME...")
            dobot.move_to(HOME_POSITION['x'], HOME_POSITION['y'], 
                         HOME_POSITION['z'], HOME_POSITION['r'], wait=True)
            time.sleep(0.5)
    except:
        pass
    
    # ÉTAPE 4: Exécuter le mouvement corrigé
    try:
        print(f"🚀 Exécution mouvement: ({x_corrige:.1f}, {y_corrige:.1f}, {z_corrige:.1f}, {r_corrige:.1f})")
        dobot.move_to(x_corrige, y_corrige, z_corrige, r_corrige, wait=True)
        time.sleep(0.3)
        
        # Vérification post-mouvement (juste pour log)
        new_pose = dobot.pose()
        new_radius = math.sqrt(new_pose[0]**2 + new_pose[1]**2)
        print(f"✅ Mouvement terminé - Position finale: rayon={new_radius:.1f}mm, Z={new_pose[2]:.1f}mm")
        
        return True, None
        
    except Exception as e:
        return False, f"Erreur mouvement: {str(e)}"


def execute_trajectory_async(trajectory):
    """Execute trajectory avec correction automatique à chaque étape"""
    global is_executing, stop_flag
    is_executing = True
    stop_flag = False
    
    try:
        print(f"\n🎯 EXÉCUTION TRAJECTOIRE: {len(trajectory)} étapes")
        print("=" * 50)
        
        for i, step in enumerate(trajectory):
            if stop_flag:
                print(f"🛑 Arrêt à l'étape {i+1}")
                break
            
            step_log = f"Étape {i+1}: "
            
            if not isinstance(step, dict):
                step_log += f"❌ Format invalide"
                print(step_log)
                continue
            
            # Gripper commands
            if 'gripper' in step:
                gripper_cmd = step['gripper']
                if isinstance(gripper_cmd, str):
                    gripper_lower = gripper_cmd.lower().strip()
                    if gripper_lower in ['close', 'closed', '1', 'true']:
                        dobot.grip(True)
                        step_log += "✋ Pince FERMÉE "
                    elif gripper_lower in ['open', 'opened', '0', 'false']:
                        dobot.grip(False)
                        step_log += "👐 Pince OUVERTE "
                time.sleep(GRIPPER_OPERATION_DELAY)
            
            # Movement commands (avec correction auto)
            movement_fields = ['x', 'y', 'z', 'r']
            has_movement = any(field in step for field in movement_fields)
            
            if has_movement:
                try:
                    x = float(step.get('x', HOME_POSITION['x']))
                    y = float(step.get('y', HOME_POSITION['y']))
                    z = float(step.get('z', HOME_POSITION['z']))
                    r = float(step.get('r', HOME_POSITION['r']))
                    
                    step_log += f"📍 Déplacement vers ({x:.1f}, {y:.1f}, {z:.1f}, {r:.1f}) "
                    
                    success, error = safe_move_to(dobot, x, y, z, r, is_trajectory=True)
                    if success:
                        step_log += "✅ OK"
                    else:
                        step_log += f"❌ ÉCHEC: {error}"
                        print(step_log)
                        break
                        
                except (ValueError, TypeError) as e:
                    step_log += f"❌ ERREUR: {e}"
                    print(step_log)
                    break
            
            # Pause commands
            if 'pause' in step:
                try:
                    pause_time = float(step['pause'])
                    if pause_time > 0:
                        actual_pause = max(MINIMUM_PAUSE_TIME, pause_time * 0.3)
                        step_log += f"⏱️ Pause {actual_pause:.2f}s "
                        time.sleep(actual_pause)
                except (ValueError, TypeError):
                    step_log += "❌ Pause invalide"
            
            print(step_log)
        
        print("=" * 50)
        print("✅ Trajectoire terminée")
        
    except Exception as e:
        print(f"❌ Erreur critique: {e}")
    finally:
        is_executing = False


# ============================================================================
# FLASK ENDPOINTS
# ============================================================================

@app.route('/')
def index():
    """Home page"""
    ip = get_ip_address()
    return jsonify({
        'server': 'Dobot Control Server - PREVENTION TOTALE',
        'version': '4.0',
        'ip': ip,
        'port': SERVER_PORT,
        'access': f'http://{ip}:{SERVER_PORT}',
        'philosophy': 'Correction automatique à la base - Pas de zone rouge',
        'safety_limits': {
            'max_radius_mm': WORKSPACE_LIMITS['max_radius'],
            'z_range_mm': WORKSPACE_LIMITS['z'],
            'r_range_deg': WORKSPACE_LIMITS['r'],
            'home_position': HOME_POSITION
        },
        'endpoints': ['/', '/status', '/manual', '/execute', '/stop']
    })


@app.route('/status')
def status():
    """Status endpoint"""
    position = None
    is_safe = True
    safety_message = "OK"
    radius = 0
    
    if dobot:
        try:
            pose = dobot.pose()
            position = {'x': pose[0], 'y': pose[1], 'z': pose[2], 'r': pose[3]}
            is_safe, safety_message, radius = check_if_position_safe(pose[0], pose[1], pose[2], pose[3])
        except:
            pass
    
    return jsonify({
        'dobot_connected': dobot is not None,
        'dobot_error': connection_error,
        'position': position,
        'position_safe': is_safe,
        'safety_message': safety_message,
        'current_radius_mm': round(radius, 1),
        'executing': is_executing,
        'recording': is_recording,
        'server_ip': get_ip_address(),
        'server_port': SERVER_PORT,
        'auto_correction': True
    })


@app.route('/manual', methods=['POST'])
def manual():
    """Manual control avec correction automatique"""
    if not dobot:
        return jsonify({'error': 'Dobot not connected'}), 503
    
    data = request.json
    if not data:
        return jsonify({'error': 'No data'}), 400
    
    command = data.get('command')
    
    if command == 'home':
        success, error = safe_move_to(dobot, HOME_POSITION['x'], HOME_POSITION['y'], 
                                     HOME_POSITION['z'], HOME_POSITION['r'])
        if success:
            return jsonify({'success': True, 'message': 'Moved to safe home position'})
        else:
            return jsonify({'error': error}), 500
    
    elif command == 'move':
        x = float(data.get('x', HOME_POSITION['x']))
        y = float(data.get('y', HOME_POSITION['y']))
        z = float(data.get('z', HOME_POSITION['z']))
        r = float(data.get('r', HOME_POSITION['r']))
        
        # La correction est automatique dans safe_move_to
        success, error = safe_move_to(dobot, x, y, z, r)
        
        if success:
            # Vérifier si la position a été corrigée
            x_c, y_c, z_c, r_c, corrige = validate_and_correct_position(x, y, z, r)
            if corrige:
                return jsonify({
                    'success': True, 
                    'message': f'Movement executed (auto-corrected from ({x},{y},{z},{r}) to ({x_c:.1f},{y_c:.1f},{z_c:.1f},{r_c:.1f}))'
                })
            else:
                return jsonify({'success': True, 'message': f'Movement executed to ({x},{y},{z},{r})'})
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
            is_safe, msg, radius = check_if_position_safe(pose[0], pose[1], pose[2], pose[3])
            return jsonify({
                'success': True,
                'position': {
                    'x': round(pose[0], 2),
                    'y': round(pose[1], 2),
                    'z': round(pose[2], 2),
                    'r': round(pose[3], 2)
                },
                'radius_mm': round(radius, 1),
                'position_safe': is_safe,
                'safety_message': msg
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif command == 'move_relative':
        dx = float(data.get('dx', 0))
        dy = float(data.get('dy', 0))
        dz = float(data.get('dz', 0))
        dr = float(data.get('dr', 0))
        
        try:
            current_pose = dobot.pose()
            new_x = current_pose[0] + dx
            new_y = current_pose[1] + dy
            new_z = current_pose[2] + dz
            new_r = current_pose[3] + dr
            
            success, error = safe_move_to(dobot, new_x, new_y, new_z, new_r)
            if success:
                return jsonify({'success': True, 'message': f'Relative movement executed'})
            else:
                return jsonify({'error': error}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    elif command == 'check_position':
        x = float(data.get('x', 0))
        y = float(data.get('y', 0))
        z = float(data.get('z', 0))
        r = float(data.get('r', 0))
        
        est_safe, message, radius = check_if_position_safe(x, y, z, r)
        x_c, y_c, z_c, r_c, corrige = validate_and_correct_position(x, y, z, r)
        
        return jsonify({
            'success': True,
            'requested': {'x': x, 'y': y, 'z': z, 'r': r},
            'is_safe': est_safe,
            'safety_message': message,
            'radius_mm': round(radius, 1),
            'auto_corrected': corrige,
            'corrected_position': {'x': round(x_c, 1), 'y': round(y_c, 1), 'z': round(z_c, 1), 'r': round(r_c, 1)} if corrige else None
        })
    
    return jsonify({'error': f'Unknown command: {command}'}), 400


@app.route('/execute', methods=['POST'])
def execute():
    """Execute trajectory"""
    global is_executing
    
    if is_executing:
        return jsonify({'error': 'Already executing'}), 400
    
    if not dobot:
        return jsonify({'error': 'Dobot not connected'}), 503
    
    data = request.json
    if not data or 'trajectory' not in data:
        return jsonify({'error': 'No trajectory'}), 400
    
    trajectory = data['trajectory']
    
    if not isinstance(trajectory, list):
        return jsonify({'error': 'Trajectory must be a list'}), 400
    
    print(f"\n🎯 RÉCEPTION TRAJECTOIRE: {len(trajectory)} étapes")
    
    thread = threading.Thread(target=execute_trajectory_async, args=(trajectory,))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'message': f'Trajectory started: {len(trajectory)} steps',
        'steps': len(trajectory),
        'auto_correction': True
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
        'auto_correction': True,
        'timestamp': datetime.now().isoformat()
    })


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    os.system('clear')
    
    print("\n" + "="*60)
    print("🤖 DOBOT CONTROL SERVER - PRÉVENTION TOTALE")
    print("="*60)
    print("\n📖 PHILOSOPHIE:")
    print("   ✅ Correction automatique des positions dangereuses")
    print("   ✅ Le robot n'entre JAMAIS en zone rouge")
    print("   ✅ Tous les mouvements sont exécutés (corrigés si besoin)")
    print("\n🔒 LIMITES (manuel Dobot p.14,67,82):")
    print(f"   • Rayon maximum: {WORKSPACE_LIMITS['max_radius']}mm")
    print(f"   • Z: {WORKSPACE_LIMITS['z'][0]}-{WORKSPACE_LIMITS['z'][1]}mm")
    print(f"   • Rotation outil: ±{WORKSPACE_LIMITS['r'][1]}°")
    print(f"   • HOME: ({HOME_POSITION['x']}, {HOME_POSITION['y']}, {HOME_POSITION['z']})")
    print("="*60)
    
    print_network_info()
    
    init_dobot()
    
    print("\n" + "="*60)
    print("🚀 SERVEUR DÉMARRÉ")
    print("="*60)
    print(f"   URL: http://{get_ip_address()}:{SERVER_PORT}")
    print("   Ctrl+C pour arrêter\n")
    
    try:
        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n👋 Arrêt du serveur")
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
    finally:
        if dobot:
            print("\n🔧 Retour à la position HOME...")
            try:
                safe_move_to(dobot, HOME_POSITION['x'], HOME_POSITION['y'], 
                           HOME_POSITION['z'], HOME_POSITION['r'])
                print("✅ Nettoyage terminé")
            except:
                print("⚠️ Nettoyage échoué")
        print("\n👋 Au revoir!\n")
