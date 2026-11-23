# Plan 218 · Aplicar autenticación y límites antes de parsear cuerpos

**Base** `ffebfc9b3c8ff91cd001b3e2cc1c085ab6acbfc6` · 2026-11-22 · **Prioridad** P1 · **Riesgo** medio · **Esfuerzo** M · **Hallazgo** C06

## Resultado

El webhook y el upload de imágenes aplican sus controles al cuerpo antes de que el parser acumule datos. Las credenciales, los tipos de respuesta y el archivo máximo admitido siguen sujetos a los contratos actuales.

## Estado y alcance

- `news_collector/serving/api.py:1032–1069` define el límite de 2 MiB. La ruta en `1562–1598` declara un cuerpo tipado. En la versión fijada de FastAPI, leer el cuerpo y resolver el parser precede a las dependencias. El test existente cubre el helper de tamaño, mientras el orden real ocurre en el borde ASGI. [FastAPI fijado](https://github.com/fastapi/fastapi/blob/0.141.1/fastapi/routing.py)
- `news_collector/serving/admin_images.py:171–209` declara `UploadFile`, campos de formulario y un límite dentro del handler. Conservar validación de contenido, límite de archivo, reglas de almacenamiento y generación OpenAPI. El límite de cuerpo debe contemplar explícitamente la envoltura multipart admitida.
- Editar `news_collector/serving/api.py`, `news_collector/serving/admin_images.py` solo si requiere conectar el control, los tests de borde en `tests/unit/serving`, y `docs/PIPELINE_CONTRACTS.md`. Si se necesita un helper compartido, limitarlo a la frontera HTTP de esas rutas. Conservar la política de autenticación local y alojada, límites de almacenamiento y esquemas de respuesta.

## Decisiones y verificación

1. Elegir un control previo al parser limitado a las dos rutas por método y fidedigno al montaje real de FastAPI, con un contador incremental de bytes. Reusar la verificación de token existente y mantener un error de autorización antes de procesar cuerpos. Para solicitudes que exceden el tamaño, devolver 413 con el formato de error actual. Documentar cómo se conserva la precedencia pública entre tamaño y autorización. Mantener autenticación fuera del mapeo de datos y decisiones editoriales.
2. Probar en la aplicación ASGI y con un adaptador de stream en memoria. Un request no autenticado debe responder sin que el parser consuma el cuerpo. Un request autorizado debe respetar el límite tanto con longitud conocida como en un stream acotado. Cuando se alcance el límite, ningún parser o sink recibe datos posteriores. Usar límites de prueba pequeños y verificar pedidos válidos, límite exacto y errores mediante fixtures. Mantener archivo permitido y formulario válidos, webhook 202 y 422 vigente. Confirmar que las rutas ajenas conservan comportamiento.
3. Ejecutar `python -m pytest tests/unit/serving/test_write_surface_bounds.py tests/unit/serving/test_admin_images_router.py --no-cov`, `make test-boundaries`, `make test-contracts`, `make quality`, `make docs-check` y el chequeo del artefacto OpenAPI del Admin. La auditoría ejecutó las pruebas focalizadas de límites existentes. Las regresiones de orden y los gates completos son aceptación del plan.

Comprobar deriva con `git diff ffebfc9b..HEAD -- news_collector/serving/api.py news_collector/serving/admin_images.py tests/unit/serving docs/PIPELINE_CONTRACTS.md`. Si el control abre una diferencia en el contrato de upload o necesita tocar rutas fuera del alcance, caracterizar el consumidor y revisar el plan antes de ampliar. Registrar el resultado en la fila 218.
