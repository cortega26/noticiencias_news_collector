# Plan 222 · Alinear el contrato de URLs de reportes

**Bases** Collector `ffebfc9b3c8ff91cd001b3e2cc1c085ab6acbfc6`, frontend `e271512f744998e25a1da3175797a25fa6c89f1e` · 2026-11-23 · **Prioridad** P2 · **Riesgo** medio · **Esfuerzo** S–M · **Hallazgo** C09

## Resultado

Las URLs que acepta el Worker para un reporte válido pueden pasar el validador de URLs del Collector. El lector recibe el error de campo antes de que se guarde un reporte con una URL que el importador rechazaría.

## Evidencia y alcance

- Frontend `workers/src/utils/validate.ts:59–83,108–138` valida con `URL` y `workers/src/handlers/report.ts:45–47,78–100` guarda la entrada original. Collector `news_collector/contracts/reader_reports.py:89–165` requiere una URL HTTP(S) absoluta con autoridad, rechaza el espacio interior y la barra invertida, y comprueba puerto y dominio. Con los validadores locales, una ruta con espacio literal pasó el Worker y falló el Collector. La misma ruta con el espacio codificado pasó ambos.
- Cambiar la validación de ambos campos en el Worker y agregar un fixture de contrato compartido. Mantener el validador de producción del Collector, el esquema R2, los valores originales aceptados, el UUID y los registros históricos. Coordinar los cambios de tests del Worker con el [plan 021](../../../noticiencias/plans/021-integridad-recepcion-reportes.md).

## Decisiones y verificación

1. Validar antes de persistir. Exigir HTTP(S) absoluto, autoridad inequívoca y puerto válido en ambos campos. Conservar la política del dominio exacto o subdominio con límite de etiqueta para el artículo y permitir destinos HTTP(S) externos como evidencia. Mantener la semántica actual de campo opcional, el límite del Worker y los escapes válidos. Validar la forma de entrada además del resultado del parser para evitar reinterpretaciones divergentes. Usar el 422 existente y comprobar que no se escribe el objeto R2 cuando falla un campo.
2. Mantener un único fixture en el frontend, `tests/fixtures/reader-report-url-contract.json`, consumido por `workers/tests/report.test.ts` y `tests/unit/contracts/test_reader_reports_contract.py`. Aplicar en Collector la convención de checkout hermano y copia de fixture en CI que utiliza `tests/test_post_schema_parity.py` y su flujo en `.github/workflows/ci.yml`. El contrato exige que todo caso aceptado por el Worker también pase la validación de URLs del Collector. Puede conservarse un límite de Collector distinto por compatibilidad histórica. Verificar el error sin escritura y el recibo válido en `workers/tests/report.handler.test.ts`.
3. Documentar la semántica y el origen del fixture en `docs/PIPELINE_CONTRACTS.md` y `docs/ci.md`. Validar los dos cambios juntos en local. Integrar el frontend con el fixture antes de que el CI del Collector requiera ese archivo. Registrar por separado las pruebas cruzadas y el despliegue del Worker.

Criterio de aceptación para los comandos declarados. Todos deben salir con código 0 y las suites de ambos repositorios deben ejecutar el fixture compartido.

- En `workers/` del frontend, `npm run typecheck && npm run test:coverage`.
- En la raíz del Collector, `make test-contracts test-boundaries docs-check`, con el modo de CI activado para exigir el fixture.

Revisar la deriva desde ambas bases. Si cambia la representación del objeto R2 antes de implementar el plan, volver a comprobar el recorrido del campo desde el Worker hasta la validación del importador.

## Evidencia local de implementación

Pasaron 90 tests del Worker con typecheck y cobertura, 311 tests de contratos, 3 de límites y la suite unitaria con el control de cobertura del Collector. Ambos leen el mismo fixture de 13 casos. La integración y el despliegue siguen pendientes.
