from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import uuid
from datetime import datetime
import os
import bcrypt

app = Flask(__name__)
# Permitimos CORS para que tu frontend (React/Flutter/HTML) pueda conectar
CORS(app)

# =========================
# CONFIGURACIÓN DE MONGODB
# =========================
# Importante: Configura "MONGO_URI" en las variables de entorno de Railway
MONGO_URI = os.environ.get("MONGO_URI")

# Configuramos un timeout de 5s para que Railway no se quede pegado si la DB no responde
cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = cliente["Estacionamiento"]

usuarios = db["usuarios"]
entrada = db["entrada"]

# Intentar crear índice único para el correo al arrancar
try:
    usuarios.create_index("correo", unique=True)
    print("Conexión a MongoDB exitosa y configuración lista ✅")
except Exception as e:
    print(f"Aviso: No se pudo verificar la DB al iniciar: {e}")

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

    # =========================
# OBTENER TODOS LOS USUARIOS
# =========================
@app.route("/usuarios", methods=["GET"])
def obtener_usuarios():
    try:
        # Buscamos todos los usuarios en la colección
        lista_usuarios = list(usuarios.find())
        
        # Formateamos la lista para que sea un JSON válido (convertimos el _id a string)
        for u in lista_usuarios:
            u["_id"] = str(u["_id"])
            # Por seguridad, no enviaremos el password en el listado
            if "password" in u:
                del u["password"]
        
        return jsonify({
            "success": True,
            "total": len(lista_usuarios),
            "usuarios": lista_usuarios
        }), 200

    except Exception as e:
        return jsonify({"success": False, "mensaje": str(e)}), 500

# --- REGISTRO ---
@app.route("/usuarios", methods=["POST"])
def crear_usuario():
    try:
        datos = request.json
        nombre = datos.get("nombre")
        correo = datos.get("correo")
        password = datos.get("password")

        if not nombre or not correo or not password:
            return jsonify({"success": False, "mensaje": "Faltan datos básicos"}), 400

        # Validar si ya existe
        if usuarios.find_one({"$or": [{"correo": correo}, {"nombre": nombre}]}):
            return jsonify({"success": False, "mensaje": "El nombre o correo ya existen"}), 409

        # Encriptar password
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)

        nuevo_usuario = {
            "nombre": nombre,
            "correo": correo,
            "password": hashed, # Se guarda como bytes en Mongo
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

# --- LOGIN ---
@app.route("/login", methods=["POST"])
def login():
    try:
        datos = request.json
        correo = datos.get("correo")
        password = datos.get("password")

        if not correo or not password:
            return jsonify({"success": False, "mensaje": "Faltan credenciales"}), 400

        usuario = usuarios.find_one({"correo": correo})

        if not usuario:
            return jsonify({"success": False, "mensaje": "Usuario no encontrado"}), 404

        # 🔑 LA CLAVE: bcrypt necesita bytes. 
        # Si Mongo guardó el hash como string o binario, hay que asegurar el tipo.
        db_password = usuario["password"]
        
        # Si por alguna razón se guardó como string, lo convertimos a bytes
        if isinstance(db_password, str):
            db_password = db_password.encode('utf-8')

        if bcrypt.checkpw(password.encode('utf-8'), db_password):
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
        print(f"Error en Login: {e}") # Esto saldrá en los logs de Railway
        return jsonify({"success": False, "mensaje": "Error interno del servidor"}), 500

# --- CONTROL DE ENTRADA (GENERAR QR) ---
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

# --- CONTROL DE SALIDA (PAGO) ---
@app.route("/salida", methods=["POST"])
def salida():
    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({"qrToken": token, "estado": "dentro"})

    if not registro:
        return jsonify({"success": False, "mensaje": "Registro no encontrado o ya salió"}), 404

    hora_salida = datetime.now()
    hora_entrada = registro["horaEntrada"]

    # Cálculo de tiempo y precio (ejemplo: 0.5 por minuto)
    diferencia = hora_salida - hora_entrada
    minutos = diferencia.total_seconds() / 60
    precio = round(minutos * 0.5, 2)

    entrada.update_one(
        {"_id": registro["_id"]},
        {"$set": {
            "horaSalida": hora_salida,
            "estado": "salida",
            "precio": precio
        }}
    )

    return jsonify({
        "success": True,
        "tiempo_minutos": round(minutos, 2),
        "precio_total": precio,
        "mensaje": "Salida registrada con éxito"
    })

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

# Comando para ejecución local (Railway usa Gunicorn, pero esto sirve para pruebas)
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)