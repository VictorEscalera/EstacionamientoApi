from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
import uuid
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

# =========================
# CONFIGURACIÓN DE MONGODB
# =========================
MONGO_URI = os.environ.get("MONGO_URI")

cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = cliente["Estacionamiento"]

usuarios = db["usuarios"]
entrada = db["entrada"]
ia = db["ia"]

try:
    usuarios.create_index("correo", unique=True)
    print("Conexión a MongoDB exitosa ✅")
except Exception as e:
    print("Error Mongo:", e)

# =========================
# API
# =========================

@app.route("/", methods=["GET"])
def inicio():
    return jsonify({"mensaje": "API funcionando 🔥"})


# =========================
# LOGIN
# =========================
@app.route("/login", methods=["POST"])
def login():

    datos = request.json
    correo = datos.get("correo")
    password = datos.get("password")

    usuario = usuarios.find_one({
        "correo": correo,
        "password": password
    })

    if usuario:
        return jsonify({
            "success": True,
            "usuario": {
                "id": str(usuario["_id"]),
                "nombre": usuario["nombre"],
                "correo": usuario["correo"]
            }
        })

    return jsonify({"success": False}), 401


# =========================
# ENTRADA IA (CONTADOR)
# =========================
@app.route("/contador-entrada", methods=["POST"])
def contador_entrada():

    nuevo = {
        "qrToken": str(uuid.uuid4()),
        "placa": "IA",
        "horaEntrada": datetime.now(),
        "horaSalida": None,
        "estado": "dentro",
        "tipo": "ia"
    }

    entrada.insert_one(nuevo)

    return jsonify({"success": True})


# =========================
# REGISTRO MANUAL
# =========================
@app.route("/entrada-manual", methods=["POST"])
def entrada_manual():

    datos = request.json
    placa = datos.get("placa")

    if not placa:
        return jsonify({"success": False})

    nuevo = {
        "qrToken": None,
        "placa": placa,
        "horaEntrada": datetime.now(),
        "horaSalida": None,
        "estado": "dentro",
        "tipo": "manual"
    }

    entrada.insert_one(nuevo)

    return jsonify({"success": True})


# =========================
# SALIDA
# =========================
@app.route("/salida", methods=["POST"])
def salida():

    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({
        "qrToken": token,
        "estado": "dentro"
    })

    if not registro:
        return jsonify({"success": False}), 404

    hora_salida = datetime.now()

    minutos = (hora_salida - registro["horaEntrada"]).total_seconds() / 60
    precio = round(minutos * 0.5, 2)

    entrada.update_one(
        {"_id": registro["_id"]},
        {
            "$set": {
                "horaSalida": hora_salida,
                "estado": "salida",
                "precio": precio
            }
        }
    )

    return jsonify({
        "success": True,
        "precio": precio
    })


# =========================
# STATS DASHBOARD
# =========================
@app.route("/stats", methods=["GET"])
def stats():

    total = 20

    ocupados = ia.count_documents({"estado": "Dentro"})
    disponibles = total - ocupados
    ingresos = 0

    return jsonify({
        "totalSpaces": total,
        "occupiedSpaces": ocupados,
        "availableSpaces": disponibles,
        "dailyIncome": 0
    })


# =========================
# LISTA VEHICULOS
# =========================
@app.route("/vehicles", methods=["GET"])
def vehicles():

    lista = list(entrada.find().sort("_id", -1).limit(20))

    resultado = []

    for v in lista:

        resultado.append({
            "id": str(v["_id"]),
            "plate": v.get("placa"),
            "status": "Dentro" if v.get("estado") == "dentro" else "Salida",
            "entryTime": str(v.get("horaEntrada")),
            "exitTime": str(v.get("horaSalida")) if v.get("horaSalida") else None
        })

    return jsonify(resultado)


# =========================
# ALERTAS
# =========================
@app.route("/alerts", methods=["GET"])
def alerts():
    return jsonify([])


# =========================
# RUN
# =========================
if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )