from django.test import SimpleTestCase

from judge.utils.compile_hints import MAX_HINTS, compile_hints


class CompileHintsTest(SimpleTestCase):
    def test_missing_iostream(self):
        hints = compile_hints("a.cpp:5:5: error: 'cout' was not declared in this scope")
        self.assertTrue(any('iostream' in h for h in hints))

    def test_curly_quotes_are_understood(self):
        hints = compile_hints('a.cpp:7:9: error: ‘total’ was not declared in this scope')
        self.assertTrue(any('khai báo' in h for h in hints))

    def test_missing_semicolon(self):
        hints = compile_hints("a.cpp:9:12: error: expected ';' before 'return'")
        self.assertTrue(any('dấu ;' in h for h in hints))

    def test_python_indentation(self):
        hints = compile_hints('  File "a.py", line 3\n    print(x)\nIndentationError: unexpected indent')
        self.assertTrue(any('thụt lề' in h for h in hints))

    def test_ansi_colours_are_ignored(self):
        hints = compile_hints("\x1b[01m\x1b[Ka.cpp:1:1: \x1b[31merror: \x1b[m\x1b[K'cin' was not declared")
        self.assertTrue(any('iostream' in h for h in hints))

    def test_nothing_matches(self):
        self.assertEqual(compile_hints('some unrelated message'), [])
        self.assertEqual(compile_hints(''), [])
        self.assertEqual(compile_hints(None), [])

    def test_hints_are_distinct_and_capped(self):
        message = '\n'.join([
            "error: 'cout' was not declared in this scope", "error: 'vector' was not declared in this scope",
            "error: 'x' was not declared in this scope", "error: expected ';' before 'y'",
            "error: expected '}' at end of input", "error: no matching function for call to 'f(int)'",
        ])
        hints = compile_hints(message)
        self.assertLessEqual(len(hints), MAX_HINTS)
        self.assertEqual(len(hints), len(set(hints)))
