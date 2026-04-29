# F5 BIG-IP ASM Policy Checklist — LightShow-NaughtyNice

## Traffic profile

| Item | Value |
|---|---|
| Protocol | HTTP (no TLS on this path) |
| Backend | Docker container via nginx (pool member) |
| Methods allowed | GET, POST |
| Max request body | 6 MB (photo upload) |
| Content-Types | `application/x-www-form-urlencoded`, `multipart/form-data` |

---

## Virtual Server / Pool

- Create a virtual server on the inside-facing IP, port 80
- Pool member: Docker host IP, port 80 (nginx listens there)
- HTTP profile on VS
- **No SSL profile needed** (HTTP only)

---

## ASM Policy settings

### Allowed URLs
| URL | Methods |
|---|---|
| `/` | GET |
| `/submit` | POST |
| `/thanks` | GET |
| `/health` | GET |
| `/static/*` | GET |

All other URLs → **Block**.

### File types (upload)
Allowed upload extensions: `jpg`, `jpeg`, `png`  
Block all others (exe, php, js, etc.) — default ASM signature covers this.

### Request body limits
Set **Maximum Request Length** to **6291456** (6 MB) on the policy.  
Requests to `/static/*` and `/health` don't need a relaxed limit — scope the
larger limit to `/submit` only.

### Evasion techniques
Keep default ASM evasion detection enabled. No relaxations needed.

### Signatures
- Enable the **Generic Detection** signature set (covers XSS, SQLi, path traversal).
- The form fields (`child_name`, `gender`, `status`) are all short, alpha strings —
  the default sig set will catch any injection attempts without false positives.
- `child_name` is user-free-text — consider a **Parameter** relaxation if legitimate
  names trigger sigs (e.g., names with apostrophes: O'Brien). Set value type to
  **User-input** with max length 40 and allow alphanumeric + apostrophe + hyphen.

### Brute-force / DoS
- Enable **Proactive Bot Defense** (or at minimum, rate limiting).
- Suggested rate limit on `/submit`: **10 requests / minute / source IP**.
  This prevents rapid form spam without impacting real users at a kiosk.

---

## Health monitor (optional but recommended)
Point a BIG-IP HTTP health monitor at `GET /health` on the pool member.  
The app returns `200 OK` when FPP is reachable, `503` when it's not — the
F5 can pull the pool member out of rotation if the Pi is down.

---

## Notes
- FPP REST API is **not** behind the F5. Flask calls it server-side on the
  internal LAN. No inbound policy changes needed for FPP.
- If you later move to HTTPS, add an SSL offload profile to the VS and update
  the nginx `X-Forwarded-Proto` header check in the Flask config.
