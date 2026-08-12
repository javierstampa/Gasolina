import json
import os
import datetime

import precios as p


def main():
    es, fecha_es = p.descargar_datos()
    with open("datos.json", "w", encoding="utf-8") as f:
        json.dump({"fecha": fecha_es, "estaciones": es}, f, ensure_ascii=False)
    print(f"Espana: {len(es)} estaciones, datos {fecha_es}")

    it, fecha_it = p.descargar_datos_italia()
    with open("datos_italia.json", "w", encoding="utf-8") as f:
        json.dump({"fecha": fecha_it, "dia": datetime.date.today().isoformat(),
                   "estaciones": it}, f, ensure_ascii=False)
    print(f"Italia: {len(it)} estaciones, datos {fecha_it}")


if __name__ == "__main__":
    main()
