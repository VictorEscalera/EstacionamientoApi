from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
import uuid
from datetime import datetime
import os
import bcrypt

app = Flask(__name__)
CORS(app)

# =========================
# CONEXIÓN MONGO (VARIABLE ENTORNO)
# =========================
MONGO_URI = os.environ.get("MONGO_URI")

cliente = MongoClient(MONGO_URI)
db = cliente["Estacionamiento"]

usuarios = db["usuarios"]
entrada = db["entrada"]

# índice único
usuarios.create_index("correo", unique=True)

# =========================
# REGISTRO
# =========================
@app.route("/usuarios", methods=["POST"])
def crear_usuario():

    datos = request.json

    nombre = datos.get("nombre")
    correo = datos.get("correo")
    password = datos.get("password")

    if not nombre or not correo or not password:
        return jsonify({
            "success": False,
            "mensaje": "Faltan datos"
        })

    # validar duplicados
    existente = usuarios.find_one({
        "$or": [
            {"correo": correo},
            {"nombre": nombre}
        ]
    })

    if existente:
        return jsonify({
            "success": False,
            "mensaje": "El nombre o correo ya existen"
        })

    # 🔐 encriptar password
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    nuevo_usuario = {
        "nombre": nombre,
        "correo": correo,
        "password": hashed,
        "rol": "usuario"
    }

    try:
        resultado = usuarios.insert_one(nuevo_usuario)
    except DuplicateKeyError:
        return jsonify({
            "success": False,
            "mensaje": "El correo ya está registrado"
        })

    return jsonify({
        "success": True,
        "mensaje": "Usuario creado correctamente",
        "id": str(resultado.inserted_id)
    })


# =========================
# LOGIN
# =========================
@app.route("/login", methods=["POST"])
def login():

    datos = request.json

    correo = datos.get("correo")
    password = datos.get("password")

    if not correo or not password:
        return jsonify({
            "success": False,
            "mensaje": "Faltan credenciales"
        })

    usuario = usuarios.find_one({"correo": correo})

    if usuario and bcrypt.checkpw(password.encode('utf-8'), usuario["password"]):

        usuario["_id"] = str(usuario["_id"])

        return jsonify({
            "success": True,
            "usuario": {
                "_id": usuario["_id"],
                "nombre": usuario["nombre"],
                "correo": usuario["correo"],
                "rol": usuario.get("rol", "usuario")
            }
        })

    return jsonify({
        "success": False,
        "mensaje": "Usuario o contraseña incorrectos"
    })


# =========================
# CREAR QR (ENTRADA)
# =========================
@app.route("/crear-qr", methods=["POST"])
def crear_qr():

    datos = request.json
    placa = datos.get("placa", "N/A")

    token = str(uuid.uuid4())

    nuevo = {
        "qrToken": token,
        "placa": placa,
        "horaEntrada": datetime.now(),
        "horaSalida": None,
        "estado": "dentro",
        "tipo": "app"
    }

    entrada.insert_one(nuevo)

    return jsonify({
        "success": True,
        "qrToken": token,
        "horaEntrada": str(nuevo["horaEntrada"])
    })


# =========================
# SALIDA
# =========================
@app.route("/salida", methods=["POST"])
def salida():

    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({"qrToken": token})

    if not registro:
        return jsonify({
            "success": False,
            "mensaje": "No encontrado"
        })

    hora_salida = datetime.now()
    hora_entrada = registro["horaEntrada"]

    tiempo = (hora_salida - hora_entrada).total_seconds() / 60
    precio = round(tiempo * 0.5, 2)

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
        "tiempo": tiempo,
        "precio": precio
    })


# =========================
# VALIDAR QR
# =========================
@app.route("/validar-qr", methods=["POST"])
def validar_qr():

    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({"qrToken": token})

    if not registro:
        return jsonify({
            "success": False,
            "mensaje": "QR no válido"
        })

    registro["_id"] = str(registro["_id"])

    return jsonify({
        "success": True,
        "data": {
            "id": registro["_id"],
            "placa": registro.get("placa", "N/A"),
            "horaEntrada": str(registro.get("horaEntrada")),
            "horaSalida": str(registro.get("horaSalida")) if registro.get("horaSalida") else None,
            "estado": registro.get("estado")
        }
    })


# =========================
# RUTA TEST
# =========================
@app.route("/", methods=["GET"])
def inicio():
    return jsonify({"mensaje": "API funcionando 🔥"})


# =========================
# RUN (RAILWAY READY)
# =========================
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))