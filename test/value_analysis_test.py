import unittest
from sliver.analysis.value_analysis import YES, NO, MAYBE, S


S4_5 = S(4, 5)
S4 = S(4)
S5 = S(5)
S6 = S(6)


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

        self.assertEqual(S4_5 < S6, YES)
        self.assertEqual(S4_5 < S5, MAYBE)
        self.assertEqual(S4 < S4_5, MAYBE)
        self.assertEqual(S5 < S4_5, NO)
        self.assertEqual(S6 < S4_5, NO)

    def test_is_within(self):
        self.assertTrue(YES.is_within(YES))
        self.assertTrue(NO.is_within(NO))
        self.assertTrue(MAYBE.is_within(MAYBE))

        self.assertTrue(YES.is_within(MAYBE))
        self.assertTrue(NO.is_within(MAYBE))

        self.assertFalse(YES.is_within(NO))
        self.assertFalse(NO.is_within(YES))
        self.assertFalse(MAYBE.is_within(YES))
        self.assertFalse(MAYBE.is_within(NO))

        self.assertTrue(S4.is_within(S4_5))
        self.assertTrue(S5.is_within(S4_5))
        self.assertFalse(S6.is_within(S4_5))
