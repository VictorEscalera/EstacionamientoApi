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
    return jsonify({
        "status": "online",
        "mensaje": "API de Estacionamiento funcionando 🔥",
        "timestamp": datetime.now()
    })

# --- OBTENER TODOS LOS USUARIOS ---
@app.route("/usuarios", methods=["GET"])
def obtener_usuarios():
    try:
        lista_usuarios = list(usuarios.find())
        for u in lista_usuarios:
            u["_id"] = str(u["_id"])
            if "password" in u:
                del u["password"]
        
        return jsonify({
            "success": True,
            "total": len(lista_usuarios),
            "usuarios": lista_usuarios
        }), 200
    except Exception as e:
        return jsonify({"success": False, "mensaje": str(e)}), 500

# --- REGISTRO (CORREGIDO) ---
@app.route("/usuarios", methods=["POST"])
def crear_usuario():
    try:
        datos = request.json
        nombre = datos.get("nombre")
        correo = datos.get("correo")
        password = datos.get("password")

        if not nombre or not correo or not password:
            return jsonify({"success": False, "mensaje": "Faltan datos básicos"}), 400

        if usuarios.find_one({"$or": [{"correo": correo}, {"nombre": nombre}]}):
            return jsonify({"success": False, "mensaje": "El nombre o correo ya existen"}), 409

        # Encriptar password y decodificar a string para guardar en Mongo limpiamente
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)

        nuevo_usuario = {
            "nombre": nombre,
            "correo": correo,
            "password": hashed.decode('utf-8'), # 🔥 Se guarda como string legible
            "rol": "usuario",
            "fecha_registro": datetime.now()
        }

        resultado = usuarios.insert_one(nuevo_usuario)
        return jsonify({
            "success": True, 
            "mensaje": "Usuario creado correctamente",
            "id": str(resultado.inserted_id)
        }), 201

    except Exception as e:
        return jsonify({"success": False, "mensaje": str(e)}), 500

# --- LOGIN (CORREGIDO) ---
@app.route("/login", methods=["POST"])
def login():
    try:
        datos = request.json
        correo = datos.get("correo")
        password_plano = datos.get("password")

        if not correo or not password_plano:
            return jsonify({"success": False, "mensaje": "Faltan credenciales"}), 400

        usuario = usuarios.find_one({"correo": correo})

        if not usuario:
            return jsonify({"success": False, "mensaje": "Usuario no encontrado"}), 404

        # Recuperar password y asegurar que sea bytes para bcrypt
        password_db = usuario["password"]
        if isinstance(password_db, str):
            password_db = password_db.encode('utf-8')

        # Comparar
        if bcrypt.checkpw(password_plano.encode('utf-8'), password_db):
            return jsonify({
                "success": True,
                "usuario": {
                    "_id": str(usuario["_id"]),
                    "nombre": usuario["nombre"],
                    "correo": usuario["correo"],
                    "rol": usuario.get("rol", "usuario")
                }
            })
        else:
            return jsonify({"success": False, "mensaje": "Contraseña incorrecta"}), 401

    except Exception as e:
        print(f"Error en Login: {e}")
        return jsonify({"success": False, "mensaje": "Error en el servidor: Invalid Salt o Formato"}), 500

# --- CONTROL DE ENTRADA (QR) ---
@app.route("/crear-qr", methods=["POST"])
def crear_qr():
    datos = request.json
    placa = datos.get("placa", "N/A")
    token = str(uuid.uuid4())

    nuevo_registro = {
        "qrToken": token,
        "placa": placa,
        "horaEntrada": datetime.now(),
        "horaSalida": None,
        "estado": "dentro",
        "tipo": "app"
    }

    entrada.insert_one(nuevo_registro)
    return jsonify({
        "success": True,
        "qrToken": token,
        "horaEntrada": nuevo_registro["horaEntrada"].strftime("%Y-%m-%d %H:%M:%S")
    })

# --- CONTROL DE SALIDA ---
@app.route("/salida", methods=["POST"])
def salida():
    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({"qrToken": token, "estado": "dentro"})

    if not registro:
        return jsonify({"success": False, "mensaje": "Registro no encontrado"}), 404

    hora_salida = datetime.now()
    diferencia = hora_salida - registro["horaEntrada"]
    minutos = diferencia.total_seconds() / 60
    precio = round(minutos * 0.5, 2)

    entrada.update_one(
        {"_id": registro["_id"]},
        {"$set": {"horaSalida": hora_salida, "estado": "salida", "precio": precio}}
    )

    return jsonify({"success": True, "tiempo_minutos": round(minutos, 2), "precio_total": precio})

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