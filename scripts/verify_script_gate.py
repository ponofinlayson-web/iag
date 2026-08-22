"""Write-time corruption gate: py_compile + junk grep + balance check."""
import re
import sys

sys.path.insert(0, "")
import py_compile

for path in sys.argv[1:]:
    py_compile.compile(path, doraise=True)
    raw = open(path, encoding="utf-8").read()
    # strip strings/comments crudely so the gate does not flag its own
    # pattern list or junk words inside docstrings
    src = re.sub(r"\"\"\".*?\"\"\"|'[^']*'|\"[^\"]*\"", "", raw, flags=re.S)
    junk = re.findall(r"placeholder|corrupt\w*|marker|XXX|TODO|FIXME|Discipline|lorem", src)
    pairs = [("{}", "{", "}"), ("()", "(", ")"), ("[]", "[", "]")]
    bal = {label: (src.count(op), src.count(cl)) for label, op, cl in pairs}
    unbal = {k: v for k, v in bal.items() if v[0] != v[1]}
    print(f"{path}: compile OK, {len(src.splitlines())} lines, "
          f"junk={junk if junk else 'none'}, unbalanced={unbal if unbal else 'none'}")
    if junk or unbal:
        sys.exit(1)
print("GATE PASS")
