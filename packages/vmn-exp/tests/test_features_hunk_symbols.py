"""hunk_symbol: the name a hunk header's context line (git's funcname) points at."""
import pytest
from vmn_exp.core.features_symbols import hunk_symbol


@pytest.mark.parametrize("context, name", [
    # Python
    ("def focal_loss(x, gamma=2):", "focal_loss"),
    ("    async def train_step(self, batch):", "train_step"),
    ("class Trainer(Base):", "Trainer"),
    ("class Config:", "Config"),
    # JavaScript / TypeScript
    ("function loadData(path) {", "loadData"),
    ("export default async function App() {", "App"),
    ("export const handler = async (event) => {", "handler"),
    ("const reducer = function (state, action) {", "reducer"),
    ("  async fetchRuns(app) {", "fetchRuns"),
    ("  render: function () {", "render"),
    ("export class RunTable extends Component {", "RunTable"),
    # Go
    ("func main() {", "main"),
    ("func (s *Server) Start(ctx context.Context) error {", "Start"),
    ("type Handler func(w http.ResponseWriter)", "Handler"),
    # Rust
    ("fn parse(input: &str) -> Result<Ast> {", "parse"),
    ("pub(crate) async unsafe fn spawn<T: Send>(t: T) {", "spawn"),
    ("impl fmt::Display for Point {", "Point"),
    ("impl<T: Clone> Stack<T> {", "Stack"),
    ("pub struct Point {", "Point"),
    # C-like
    ("static int count_lines(const char *path)", "count_lines"),
    ("struct node *make_node(int value)", "make_node"),
    ("void Foo::bar(int x) const", "bar"),
    ("public static void main(String[] args) {", "main"),
    # others
    ("    def self.build(opts)", "build"),
    ("override fun onCreate(savedInstanceState: Bundle?) {", "onCreate"),
])
def test_the_identifier_of_a_signature_is_extracted(context, name):
    assert hunk_symbol(context) == name


@pytest.mark.parametrize("context", [
    "if __name__ == \"__main__\":",
    "if (argc > 1) {",
    "app.listen(3000);",
    "@app.route(\"/runs\")",
    "while (true) {",
])
def test_statements_fall_back_to_the_trimmed_context_text(context):
    assert hunk_symbol("  " + context + "  ") == context


def test_the_fallback_text_is_cut_at_80_characters():
    context = "X = [" + "1, " * 60 + "]"
    assert hunk_symbol(context) == context[:80].rstrip()


@pytest.mark.parametrize("context", ["", "   ", "\t"])
def test_an_empty_context_has_no_symbol(context):
    assert hunk_symbol(context) is None
