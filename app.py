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

try:
    usuarios.create_index("correo", unique=True)
    print("Conexión a MongoDB exitosa ✅")
except Exception as e:
    print("Error Mongo:", e)

# =========================
# TEST
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

    usuario = usuarios.find_one({
        "correo": datos.get("correo"),
        "password": datos.get("password")
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
# CREAR QR (APP)
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
        "precio": 0,
        "pagado": False,
        "tipo": "app"
    }

    entrada.insert_one(nuevo)

    return jsonify({
        "success": True,
        "qrToken": token,
        "horaEntrada": str(nuevo["horaEntrada"])
    })

# =========================
# ENTRADA IA
# =========================
@app.route("/contador-entrada", methods=["POST"])
def contador_entrada():

    nuevo = {
        "qrToken": str(uuid.uuid4()),
        "placa": "IA",
        "horaEntrada": datetime.now(),
        "horaSalida": None,
        "estado": "dentro",
        "precio": 0,
        "pagado": False,
        "tipo": "ia"
    }

    entrada.insert_one(nuevo)

    return jsonify({"success": True})

# =========================
# ENTRADA MANUAL
# =========================
@app.route("/entrada-manual", methods=["POST"])
def entrada_manual():
    datos = request.json
    placa = datos.get("placa")

    if not placa:
        return jsonify({"success": False, "mensaje": "Placa requerida"}), 400

    nuevo = {
        "qrToken": str(uuid.uuid4()),
        "placa": placa,
        "horaEntrada": datetime.now(),
        "horaSalida": None,
        "estado": "dentro",
        "precio": 0,
        "pagado": False,
        "tipo": "manual"
    }

    resultado = entrada.insert_one(nuevo)

    return jsonify({
        "success": True,
        "id": str(resultado.inserted_id),
        "qrToken": nuevo["qrToken"]
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
        return jsonify({"success": False}), 404

    return jsonify({
        "success": True,
        "data": {
            "id": str(registro["_id"]),
            "placa": registro["placa"],
            "estado": registro["estado"],
            "horaEntrada": str(registro["horaEntrada"]),
            "qrToken": registro["qrToken"]
        }
    })

# =========================
# SALIDA (COBRO)
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
        return jsonify({"success": False, "mensaje": "Vehículo no encontrado o ya salió"}), 404

    hora_salida = datetime.now()

    minutos = (hora_salida - registro["horaEntrada"]).total_seconds() / 60
    precio = round(minutos * 0.5, 2)

    entrada.update_one(
        {"_id": registro["_id"]},
        {"$set": {
            "horaSalida": hora_salida,
            "estado": "salida",
            "precio": precio,
            "pagado": True
        }}
    )

    return jsonify({
        "success": True,
        "tiempo_min": round(minutos, 2),
        "precio": precio
    })

# =========================
# VEHÍCULOS
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
            "exitTime": str(v.get("horaSalida")) if v.get("horaSalida") else None,
            "price": v.get("precio", 0),
            "qrToken": v.get("qrToken"),
            "pagado": v.get("pagado", False)
        })

    return jsonify(resultado)

# =========================
# STATS
# =========================
@app.route("/stats", methods=["GET"])
def stats():
    total = 20

    ocupados = entrada.count_documents({"estado": "dentro"})
    disponibles = total - ocupados

    pipeline = [
        {"$match": {"pagado": True}},
        {"$group": {"_id": None, "total": {"$sum": "$precio"}}}
    ]

    result = list(entrada.aggregate(pipeline))
    ingresos = result[0]["total"] if result else 0

    return jsonify({
        "totalSpaces": total,
        "occupiedSpaces": ocupados,
        "availableSpaces": disponibles,
        "dailyIncome": ingresos
    })

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
    app.run(host="0.0.0.0", port=port)