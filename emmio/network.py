import requests


def query(request):
    request["action"] = "query"
    request["format"] = "json"
    last_continue = {}
    while True:
        # Clone original request
        req = request.copy()
        # Modify it with the values returned in the 'continue' section of the
        # last result.
        req.update(last_continue)
        # Call API
        result = requests.get(
            "https://en.wikipedia.org/w/api.php", params=req
        ).json()
        if "error" in result:
            raise Exception(result["error"])
        if "warnings" in result:
            print(result["warnings"])
        if "query" in result:
            yield result["query"]
        if "continue" not in result:
            break
        last_continue = result["continue"]


for result in query({"generator": "allpages", "prop": "links"}):
    "process result data"
