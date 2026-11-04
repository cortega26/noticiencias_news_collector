# Pruebas del plan 209

Las regresiones se incorporarán a `tests/unit/editorial/test_fact_check_verification.py` usando la ruta real `prepare_article`, con dobles solo en proveedores. Deben distinguir un veredicto `uncertain` válido de un verificador inaccesible o incompleto, y probar la última verificación después de una reparación.
