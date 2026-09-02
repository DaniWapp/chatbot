#!/usr/bin/env python
"""Evaluación académica del pipeline RAG.

Ejecuta el conjunto de preguntas de prueba (evaluation/test_questions.json)
contra el chatbot y verifica:
  - Si recuperó información relevante cuando debía (should_have_info).
  - Si la respuesta contiene las palabras clave esperadas.
  - Si citó la fuente esperada.
  - Si reconoció correctamente cuando NO tiene información suficiente.

Requiere GROQ_API_KEY configurada (usa el LLM real) y el índice ya construido
(ejecutar antes `python scripts/ingest.py`).

Uso:
    python evaluation/evaluate.py
"""
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services import chat_service  # noqa: E402

QUESTIONS_PATH = Path(__file__).resolve().parent / "test_questions.json"


def evaluate_one(item: dict) -> dict:
    session_id = f"eval-{uuid.uuid4().hex[:8]}"
    response = chat_service.answer_question(session_id, item["question"])

    # Normaliza espacios antes de "%" (el LLM a veces usa espacio normal o un
    # espacio angosto Unicode " " antes del símbolo, p. ej. "80 %")
    # para que la comparación de palabras clave no falle por formato.
    answer_lower = re.sub(r"\s+%", "%", response.answer.lower())
    keywords_found = [
        kw for kw in item.get("expected_answer_contains", []) if kw.lower() in answer_lower
    ]
    keywords_ok = (
        len(keywords_found) == len(item.get("expected_answer_contains", []))
        if item["should_have_info"]
        else True
    )

    source_docs = [s.document for s in response.sources]
    source_ok = (
        (item["expected_source"] in source_docs) if item["should_have_info"] else len(source_docs) == 0
    )

    info_flag_ok = response.has_sufficient_info == item["should_have_info"]

    passed = keywords_ok and source_ok and info_flag_ok

    return {
        "id": item["id"],
        "question": item["question"],
        "passed": passed,
        "info_flag_ok": info_flag_ok,
        "keywords_ok": keywords_ok,
        "source_ok": source_ok,
        "answer": response.answer,
        "sources": source_docs,
        "metrics": response.metrics.model_dump(),
    }


def main() -> None:
    if not settings.GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY no configurada. Copia .env.example a .env y agrega tu clave.")
        sys.exit(1)

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    results = []

    print(f"Ejecutando {len(questions)} preguntas de evaluación...\n")
    for item in questions:
        result = evaluate_one(item)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {result['id']}: {result['question']}")
        if not result["passed"]:
            print(f"         info_flag_ok={result['info_flag_ok']} keywords_ok={result['keywords_ok']} source_ok={result['source_ok']}")
            print(f"         Respuesta: {result['answer'][:200]}")
            print(f"         Fuentes: {result['sources']}")

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    avg_total_ms = sum(r["metrics"]["total_ms"] for r in results) / total if total else 0

    print("\n" + "=" * 50)
    print(f"Resultado: {passed}/{total} preguntas correctas ({passed / total * 100:.0f}%)")
    print(f"Tiempo promedio por respuesta: {avg_total_ms:.0f} ms")
    print("=" * 50)

    report_path = Path(__file__).resolve().parent / "last_report.json"
    report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte detallado guardado en: {report_path}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
