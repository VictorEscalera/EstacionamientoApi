from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import uuid
from datetime import datetime
import os
import bcrypt

app = Flask(__name__)
# CORS habilitado para conectar con Ionic/Frontend
CORS(app)

# =========================
# CONFIGURACIÓN DE MONGODB
# =========================
MONGO_URI = os.environ.get("MONGO_URI")

# Timeout de 5s para evitar que el despliegue se congele si la DB no responde
cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = cliente["Estacionamiento"]

usuarios = db["usuarios"]
entrada = db["entrada"]

# Crear índice único para el correo
try:
    usuarios.create_index("correo", unique=True)
    print("Conexión a MongoDB exitosa ✅")
except Exception as e:
    print(f"Aviso: Error de conexión inicial: {e}")

# =========================
# RUTAS DE LA API
# =========================

@app.route("/", methods=["GET"])
def inicio():
    return jsonify({"mensaje": "API de Estacionamiento (Modo Simple) funcionando 🔥"})

# --- REGISTRO ---
@app.route("/usuarios", methods=["POST"])
def crear_usuario():
    try:
        datos = request.json
        nombre = datos.get("nombre")
        correo = datos.get("correo")
        password = datos.get("password")
        rol = datos.get("rol", "usuario") # Permite enviar rol desde el JSON

        if not nombre or not correo or not password:
            return jsonify({"success": False, "mensaje": "Faltan datos"}), 400

        if usuarios.find_one({"correo": correo}):
            return jsonify({"success": False, "mensaje": "El correo ya existe"}), 409

        nuevo_usuario = {
            "nombre": nombre,
            "correo": correo,
            "password": password, # Se guarda como texto normal
            "rol": rol,
            "fecha_registro": datetime.now()
        }

        usuarios.insert_one(nuevo_usuario)
        return jsonify({"success": True, "mensaje": "Usuario creado correctamente"}), 201
    except Exception as e:
        return jsonify({"success": False, "mensaje": str(e)}), 500

# --- LOGIN ---
@app.route("/login", methods=["POST"])
def login():
    try:
        datos = request.json
        correo = datos.get("correo")
        password = datos.get("password")

        # Buscamos que coincidan correo Y password exactamente
        usuario = usuarios.find_one({"correo": correo, "password": password})

        if usuario:
            return jsonify({
                "success": True,
                "usuario": {
                    "_id": str(usuario["_id"]),
                    "nombre": usuario["nombre"],
                    "correo": usuario["correo"],
                    "rol": usuario.get("rol", "usuario")
                }
            })
        
        return jsonify({"success": False, "mensaje": "Correo o contraseña incorrectos"}), 401
    except Exception as e:
        return jsonify({"success": False, "mensaje": "Error en el servidor"}), 500

# --- CONTROL DE ENTRADA (QR) ---
@app.route("/crear-qr", methods=["POST"])
def crear_qr():
    datos = request.json
    placa = datos.get("placa", "N/A")
    token = str(uuid.uuid4())
    nuevo = {
        "qrToken": token, "placa": placa, "horaEntrada": datetime.now(),
        "horaSalida": None, "estado": "dentro", "tipo": "app"
    }
    entrada.insert_one(nuevo)
    return jsonify({"success": True, "qrToken": token, "horaEntrada": str(nuevo["horaEntrada"])})

# --- CONTROL DE SALIDA ---
@app.route("/salida", methods=["POST"])
def salida():
    datos = request.json
    token = datos.get("qrToken")
    registro = entrada.find_one({"qrToken": token, "estado": "dentro"})
    if not registro:
        return jsonify({"success": False, "mensaje": "No encontrado"}), 404
    
    hora_salida = datetime.now()
    minutos = (hora_salida - registro["horaEntrada"]).total_seconds() / 60
    precio = round(minutos * 0.5, 2)
    entrada.update_one({"_id": registro["_id"]}, {"$set": {"horaSalida": hora_salida, "estado": "salida", "precio": precio}})
    return jsonify({"success": True, "tiempo": minutos, "precio": precio})

# --- VALIDACIÓN DE QR ---
@app.route("/validar-qr", methods=["POST"])
def validar_qr():
    datos = request.json
    token = datos.get("qrToken")
    registro = entrada.find_one({"qrToken": token})

    if not registro:
        return jsonify({"success": False, "mensaje": "QR no válido"}), 404

    return jsonify({
        "success": True,
        "data": {
            "id": str(registro["_id"]),
            "placa": registro.get("placa"),
            "estado": registro.get("estado"),
            "horaEntrada": str(registro.get("horaEntrada"))
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)