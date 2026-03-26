from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
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

TOTAL_LUGARES = 20

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
# VERIFICAR ESPACIO
# =========================
@app.route("/contador-entrada", methods=["POST"])
def contador_entrada():

    ocupados = ia.count_documents({"estado": "Entrada"})

    if ocupados >= TOTAL_LUGARES:
        return jsonify({
            "success": False,
            "message": "🚫 Estacionamiento lleno"
        }), 403

    return jsonify({
        "success": True,
        "ocupados": ocupados
    })


# =========================
# ENTRADA MANUAL
# =========================
@app.route("/entrada-manual", methods=["POST"])
def entrada_manual():

    ocupados = ia.count_documents({"estado": "Entrada"})

    if ocupados >= TOTAL_LUGARES:
        return jsonify({
            "success": False,
            "message": "🚫 Estacionamiento lleno"
        }), 403

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
        return jsonify({"success": False}), 404

    hora_salida = datetime.now()

    # 🔥 COBRO PARA DEMO → 20 pesos cada 5 segundos
    segundos = (hora_salida - registro["horaEntrada"]).total_seconds()
    precio = round((segundos / 5) * 20, 2)

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
# STATS (INGRESOS)
# =========================
@app.get("/stats")
def get_stats():

    total_spaces = TOTAL_LUGARES

    occupied = ia.count_documents({
        "estado": "Entrada"
    })

    if occupied > total_spaces:
        occupied = total_spaces

    available = total_spaces - occupied
    if available < 0:
        available = 0

    # 💰 INGRESOS DEL DÍA
    hoy = datetime.now().date()

    ingresos = entrada.aggregate([
        {
            "$match": {
                "estado": "salida",
                "horaSalida": {
                    "$gte": datetime.combine(hoy, datetime.min.time())
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$precio"}
            }
        }
    ])

    total_income = 0
    for i in ingresos:
        total_income = round(i["total"], 2)

    return {
        "totalSpaces": total_spaces,
        "occupiedSpaces": occupied,
        "availableSpaces": available,
        "dailyIncome": total_income
    }


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
            "plate": v.get("placa") or "N/A",  # 🔥 FIX
            "status": "Dentro" if v.get("estado") == "dentro" else "Salida",
            "entryTime": str(v.get("horaEntrada")),
            "exitTime": str(v.get("horaSalida")) if v.get("horaSalida") else None,
            "qrToken": v.get("qrToken"),
            "price": v.get("precio", 0)
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
