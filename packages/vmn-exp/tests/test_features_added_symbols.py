"""Symbols from the definitions a patch adds or removes, not only from hunk
headers: a hunk header names the function *above* a change, so a function
appended below another one, or a whole new file, would otherwise go unnamed."""
import time

import pytest
from test_features_git_patches import _write, repo  # noqa: F401
from vmn_exp.core.features import features_from_patches
from vmn_exp.core.features_symbols import defined_symbol


def _symbols(text):
    return features_from_patches([text])["changed"]["symbols"]


def test_a_function_appended_below_another_is_named_with_the_hunk_context(repo):  # noqa: F811
    path, git = repo
    body = "".join(f"    v{i} = {i}\n" for i in range(6))
    _write(path, {"loss.py": f"import math\n\n\ndef cross_entropy(x):\n{body}    return x\n"})
    git("add", "-A")
    git("commit", "-qm", "loss")
    with open(path / "loss.py", "a") as f:
        f.write("\n\ndef focal_loss(x, gamma=2):\n    return x * gamma\n")
    diff = git("diff", "HEAD")
    assert "@@ def cross_entropy(x):" in diff
    assert _symbols(diff) == ["loss.py::cross_entropy", "loss.py::focal_loss"]


def test_a_new_files_definitions_are_its_symbols(repo):  # noqa: F811
    path, git = repo
    (path / "models").mkdir()
    (path / "web").mkdir()
    _write(path, {
        "models/net.py": "class Net:\n    async def forward(self, x):\n        return x\n",
        "web/app.ts": ("export const load = async (path: string): Promise<void> => {\n};\n\n"
                       "export function save(x) {\n  return x;\n}\n"),
        "README.md": "# Net\n\nclass weights for the long tail; call train(x) to start.\n",
    })
    git("add", "-A")
    diff = git("diff", "--cached")
    assert "@@ -0,0 +1," in diff
    assert sorted(_symbols(diff)) == ["models/net.py::Net", "models/net.py::forward",
                                      "web/app.ts::load", "web/app.ts::save"]


def test_removed_definitions_are_symbols_too():
    text = ("diff --git a/loss.py b/loss.py\n--- a/loss.py\n+++ b/loss.py\n"
            "@@ -10,4 +10,0 @@ class Losses:\n-    def old_loss(self, x):\n-        return x\n"
            " \n")
    assert _symbols(text) == ["loss.py::Losses", "loss.py::old_loss"]


def test_context_lines_and_a_binary_payload_define_nothing():
    text = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,3 @@\n"
            " def kept(x):\n-    a = 1\n+    a = 2\n")
    assert _symbols(text) == []


@pytest.mark.parametrize("path, line, name", [
    ("a.py", "def focal_loss(x, gamma=2):", "focal_loss"),
    ("a.py", "    async def forward(self, x):", "forward"),
    ("a.py", "class Net(nn.Module):", "Net"),
    ("a.py", "class Config:", "Config"),
    ("a.pyi", "def f[T](x: T) -> T: ...", "f"),
    ("a.js", "function loadData(path) {", "loadData"),
    ("a.js", "export default async function* stream(x) {", "stream"),
    ("a.js", "const load = (path) => {", "load"),
    ("a.ts", "export const load = async (p: string): Promise<void> => {", "load"),
    ("a.js", "let handler = function (e) {", "handler"),
    ("a.js", "  render() {", "render"),
    ("a.js", "  static create(x) {", "create"),
    ("a.js", "class Foo extends Bar {", "Foo"),
    ("a.go", "func (s *Server) Stop(ctx context.Context) error {", "Stop"),
    ("a.go", "func main() {", "main"),
    ("a.go", "type Server struct {", "Server"),
    ("a.rs", "pub fn parse(input: &str) -> usize {", "parse"),
    ("a.rs", "impl Display for Token {", "Token"),
    ("a.rs", "pub(crate) struct Lexer<'a> {", "Lexer"),
    ("a.c", "static int count_lines(const char *path)", "count_lines"),
    ("a.c", "struct node *make_node(int v) {", "make_node"),
    ("a.cc", "void Trainer::step(int n) {", "step"),
    ("a.cc", "std::vector<int> ids(const Batch& b) const {", "ids"),
    ("a.java", "    public List<String> names(int n) {", "names"),
    ("a.java", "    Trainer(int n) {", "Trainer"),
    ("a.java", "    private static void main(String[] args) {", "main"),
    ("a.kt", "    override fun train(x: Int): Int {", "train"),
    ("a.rb", "  def self.build(opts)", "build"),
    ("a.sh", "function deploy {", "deploy"),
])
def test_a_definition_line_names_what_it_defines(path, line, name):
    assert defined_symbol(line, path) == name


@pytest.mark.parametrize("path, line", [
    ("a.py", "    loss = compute(x)"),
    ("a.py", "    return train(x)"),
    ("a.py", "    raise ValueError(x)"),
    ("a.py", "    train(x)"),
    ("a.py", "    @decorator(x)"),
    ("a.py", "    class weights for the long tail (see the paper)"),
    ("a.py", "    type of the input"),
    ("a.py", "    # def commented_out(x):"),
    ("a.md", "def focal_loss(x):"),
    ("a.md", "See the function focal_loss(x) for details."),
    ("a.txt", "class Net:"),
    ("a.json", '  "function": "train(x)",'),
    ("a.js", 'describe("loss", () => {'),
    ("a.js", "beforeEach(async () => {"),
    ("a.js", "  if (ready) {"),
    ("a.js", "  } else if (x) {"),
    ("a.js", "const total = (a + b) * 2;"),
    ("a.js", "  return render(x);"),
    ("a.js", "  model.fit(x)"),
    ("a.js", " * Returns the focal(x) loss."),
    ("a.c", "    printf(\"%d\", count_lines(path));"),
    ("a.c", "struct node head;"),
    ("a.c", "int total = count(x);"),
    ("a.cc", "TEST(LossTest, Focal) {"),
    ("a.java", "    synchronized (lock) {"),
    ("a.java", "    try (Reader r = open()) {"),
    ("a.java", "    @Override"),
    ("a.go", "\tif err := run(ctx); err != nil {"),
    ("a.go", "\tdefer close(ch)"),
    ("a.go", "// func old() {"),
    ("a.rs", "    let n = parse(input);"),
])
def test_calls_statements_comments_and_prose_define_nothing(path, line):
    assert defined_symbol(line, path) is None


HEX = "0123456789abcdef" * 3200  # a 51200-character data blob


def _new_file(path, lines):
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\nindex 0000000..1111111\n"
            f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
            + "".join(f"+{line}\n" for line in lines))


def _seconds(patch):
    started = time.monotonic()
    features_from_patches([patch])
    return time.monotonic() - started


@pytest.mark.parametrize("path, line", [
    ("src/blob.ts", f'const sig = "{HEX}".match(/../g)'),
    ("src/blob.js", "a" * 50000 + "-b(x) {"),
    ("src/blob.c", f"x {HEX} + (y) {{"),
    ("src/blob.go", "func" + " " * 30000 + "-"),
    ("src/blob.rs", "impl a" + " " * 30000 + "-"),
], ids=["hex-string", "word-run", "hex-expression", "func-spaces", "impl-spaces"])
def test_a_long_content_line_is_read_quickly(path, line):
    assert _seconds(_new_file(path, [line])) < 1.0


def test_a_data_file_of_many_long_lines_is_read_quickly():
    line = f'const s = "{HEX[:464]}".match(/../g)'
    assert _seconds(_new_file("src/data.ts", [line] * 2000)) < 0.5
