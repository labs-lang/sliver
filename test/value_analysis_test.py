import unittest
from sliver.utils.value_analysis import YES, NO, MAYBE, S


class TestStripes(unittest.TestCase):
    def setUp(self) -> None:
        pass

    def test_less_than(self):
        self.assertEqual(NO < YES, YES)
        self.assertEqual(NO < NO, NO)
        self.assertEqual(NO < MAYBE, MAYBE)
        
        self.assertEqual(YES < YES, NO)
        self.assertEqual(YES < NO, NO)
        self.assertEqual(YES < MAYBE, NO)

        self.assertEqual(MAYBE < YES, MAYBE)
        self.assertEqual(MAYBE < NO, NO)
        self.assertEqual(MAYBE < MAYBE, MAYBE)

        self.assertEqual(S(4, 5) < S(6), YES)
        self.assertEqual(S(4, 5) < S(5), MAYBE)
        self.assertEqual(S(4) < S(4, 5), MAYBE)
        self.assertEqual(S(5) < S(4, 5), NO)
        self.assertEqual(S(6) < S(4, 5), NO)
