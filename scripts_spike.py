import json, sys, time
from pathlib import Path
from cvv.ingest import read
from cvv.extract import extract

model = sys.argv[1] if len(sys.argv) > 1 else "qwen3:1.7b"
from cvv.providers import OllamaProvider

doc = read(Path("docs/CV-SDE-AR.pdf"))
t0 = time.time()
g, counts = extract(doc, provider=OllamaProvider(model), graph_id="cg_" + model.replace(":", "_"))
elapsed = time.time() - t0

Path(f"out/graph-{model.replace(':','_')}.json").write_text(
    g.model_dump_json(indent=2, exclude_none=False)
)
print(json.dumps({"model": model, "seconds": round(elapsed, 1), "proposed": counts,
                  "kept": len(g.claims), "dropped": g.extraction_meta.span_failures}, indent=2))
