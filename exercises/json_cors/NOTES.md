Q1 — In Stage B, did the request reach the server?

Evidence: the shell 1 access log at the moment of the failed click, and the console line that reported a network failure sitting next to a 200.

Yes. The request arrived, the server ran the query, and it returned 200 with the full JSON body. From the server's side nothing went wrong and nothing was refused. The failure happened afterwards, inside the browser, on the receiving end.

The same-origin policy is therefore not enforced at the server. The server served the data unconditionally. Enforcement happens in the browser, after a successful response, at the point where the page tries to read it.

It also isn't protecting the server. It's protecting the user: stopping a page loaded from 8001 from quietly reading data at 8000 that the user never intended it to touch. A guardrail on what pages may do with someone's browser, not a lock the server put on its own data.

Q2 — Why does the console know the reason and the page does not?

Evidence: the console message named both origins, said the request was blocked by CORS policy, and named the missing Access-Control-Allow-Origin header. The page's catch block received a bare TypeError with no origins, no mention of CORS, and no header name.

The gap is deliberate. If page JavaScript could read why a cross-origin request failed, that error would itself become a cross-origin information leak: whether a server exists at that address, what it responded with, whether a particular header was present. Probing like that is precisely what the same-origin policy exists to prevent, so the browser refuses to tell the page anything.

The developer still needs to debug, so the full reason goes to the console, which only a human at the keyboard can see. Same event, two audiences: verbose to the developer, blind to the code.

Q3 — What changed between the Stage B and Stage C curl output?

Evidence: the two curl -i headers side by side. The diff is one line. Stage C carries Access-Control-Allow-Origin: http://localhost:8001; Stage B doesn't. Status, content type, content length and body are identical.

curl got the same 200 and the same data in both stages. It never cared whether the header was present. The only client whose behaviour changed was the browser.

So CORS is not server-side access control. Server-side access control would have withheld something when access wasn't allowed — a 403, an empty body, fewer rows. The server did none of that; it sent all 48 rows both times. The header doesn't guard the data. It's a message to the browser saying a page from this origin may read this response. The gate is in the browser and the header only tells it which way to swing.

What was protected was never the data. It was the read by a cross-origin page.

Q4 — What did the browser send in Stage D that appears nowhere in page.html?

Evidence: an OPTIONS request in the Stage D shell 1 log, with no GET following it until do_OPTIONS existed. There is no OPTIONS anywhere in page.html — the code only calls fetch, which issues a GET.

Adding X-Requested-With pushed the request out of the browser's "simple request" category; only a short allow-list of headers keeps a request simple. For any non-simple cross-origin request the browser generates an extra HTTP round trip by itself: the preflight. An OPTIONS request asking the server in advance whether a page from this origin may send a GET carrying that header. Only if the response approves does the real GET go out.

This is the sharper half of "what does the browser do that curl does not." curl sends exactly what you type, once. The browser manufactures a whole request that exists nowhere in the source, before it is willing to let your request leave at all.
