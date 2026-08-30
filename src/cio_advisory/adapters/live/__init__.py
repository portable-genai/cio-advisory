"""``live`` profile adapters: real research, every model call the Gemini API.

Under live, house-view themes come from Gemini-grounded research over real published
market commentary (cited to their public sources) and clients and portfolios are whatever
the audience registers, never the fictional samples. Everything else reuses the SDK-free
local adapters, so custody of the index and the audit trail stays on the machine.

There is deliberately no local model server. A system whose house views are researched
from the open web cannot answer without leaving the data centre, so generating the
narrative on a laptop model beside that research would describe a deployment nobody
would buy (org decision, 2026-08-30). The profile therefore needs Application Default
Credentials and a ``GOOGLE_CLOUD_PROJECT``, and the UI provenance banner states that the
runtime is local while the model is Gemini.
"""
