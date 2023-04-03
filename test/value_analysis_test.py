import unittest
from sliver.analysis.domains import Stripes


S4_5 = Stripes.abstract(4, 5)
S4 = Stripes.abstract(4)
S5 = Stripes.abstract(5)
S6 = Stripes.abstract(6)


class TestStripes(unittest.TestCase):
    def setUp(self) -> None:
        pass

    def test_less_than(self):
        self.assertEqual(Stripes.NO < Stripes.YES, Stripes.YES)
        self.assertEqual(Stripes.NO < Stripes.NO, Stripes.NO)
        self.assertEqual(Stripes.NO < Stripes.MAYBE, Stripes.MAYBE)

        self.assertEqual(Stripes.YES < Stripes.YES, Stripes.NO)
        self.assertEqual(Stripes.YES < Stripes.NO, Stripes.NO)
        self.assertEqual(Stripes.YES < Stripes.MAYBE, Stripes.NO)

        self.assertEqual(Stripes.MAYBE < Stripes.YES, Stripes.MAYBE)
        self.assertEqual(Stripes.MAYBE < Stripes.NO, Stripes.NO)
        self.assertEqual(Stripes.MAYBE < Stripes.MAYBE, Stripes.MAYBE)

        self.assertEqual(S4_5 < S6, Stripes.YES)
        self.assertEqual(S4_5 < S5, Stripes.MAYBE)
        self.assertEqual(S4 < S4_5, Stripes.MAYBE)
        self.assertEqual(S5 < S4_5, Stripes.NO)
        self.assertEqual(S6 < S4_5, Stripes.NO)

    def test_is_within(self):
        self.assertTrue(Stripes.YES.is_within(Stripes.YES))
        self.assertTrue(Stripes.NO.is_within(Stripes.NO))
        self.assertTrue(Stripes.MAYBE.is_within(Stripes.MAYBE))

        self.assertTrue(Stripes.YES.is_within(Stripes.MAYBE))
        self.assertTrue(Stripes.NO.is_within(Stripes.MAYBE))

        self.assertFalse(Stripes.YES.is_within(Stripes.NO))
        self.assertFalse(Stripes.NO.is_within(Stripes.YES))
        self.assertFalse(Stripes.MAYBE.is_within(Stripes.YES))
        self.assertFalse(Stripes.MAYBE.is_within(Stripes.NO))

        self.assertTrue(S4.is_within(S4_5))
        self.assertTrue(S5.is_within(S4_5))
        self.assertFalse(S6.is_within(S4_5))
