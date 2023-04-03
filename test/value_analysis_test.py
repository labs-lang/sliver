import unittest

from sliver.analysis.domains import Sign, Stripes

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


NATURAL = Sign(plus=True, zero=True)
NONPOSITIVE = Sign(zero=True, minus=True)
NONZERO = Sign(plus=True, minus=True)


class TestSign(unittest.TestCase):

    def test_invert(self):
        self.assertEqual(~Sign.YES, Sign.NO)
        self.assertEqual(~Sign.NO, Sign.YES)
        self.assertEqual(~Sign.MAYBE, Sign.MAYBE)

    def test_add(self):
        self.assertEqual(Sign.YES + NATURAL, Sign.YES)
        self.assertEqual(Sign.YES + Sign.NEG, Sign.TOP)
        self.assertEqual(Sign.YES + NONPOSITIVE, Sign.TOP)
        self.assertEqual(Sign.YES + NONZERO, Sign.TOP)
        self.assertEqual(Sign.YES + Sign.YES, Sign.YES)
        self.assertEqual(Sign.YES + Sign.TOP, Sign.TOP)
        self.assertEqual(Sign.YES + Sign.NO, Sign.YES)

        self.assertEqual(Sign.NEG + NATURAL, Sign.TOP)
        self.assertEqual(Sign.NEG + Sign.NEG, Sign.NEG)
        self.assertEqual(Sign.NEG + NONPOSITIVE, Sign.NEG)
        self.assertEqual(Sign.NEG + NONZERO, Sign.TOP)
        self.assertEqual(Sign.NEG + Sign.YES, Sign.TOP)
        self.assertEqual(Sign.NEG + Sign.TOP, Sign.TOP)
        self.assertEqual(Sign.NEG + Sign.NO, Sign.NEG)

        self.assertEqual(Sign.NO + Sign.NO, Sign.NO)
        self.assertEqual(Sign.TOP + Sign.TOP, Sign.TOP)

    def test_mul(self):
        self.assertEqual(Sign.YES * Sign.YES, Sign.YES)
        self.assertEqual(Sign.YES * Sign.NO, Sign.NO)
        self.assertEqual(Sign.YES * Sign.NEG, Sign.NEG)
        self.assertEqual(Sign.NEG * Sign.YES, Sign.NEG)
        self.assertEqual(Sign.NEG * Sign.NEG, Sign.YES)
        self.assertEqual(Sign.NEG * Sign.NO, Sign.NO)
        self.assertEqual(Sign.NO * Sign.NO, Sign.NO)

    def test_or(self):
        self.assertEqual(Sign.YES | Sign.YES, Sign.YES)
        self.assertEqual(Sign.YES | Sign.NO, NATURAL)
        self.assertEqual(Sign.YES | Sign.NEG, NONZERO)
        self.assertEqual(Sign.NEG | Sign.YES, NONZERO)
        self.assertEqual(Sign.NEG | Sign.NEG, Sign.NEG)
        self.assertEqual(Sign.NEG | Sign.NO, NONPOSITIVE)
        self.assertEqual(Sign.NO | Sign.NO, Sign.NO)

    def test_neg(self):
        self.assertEqual(-NATURAL, NONPOSITIVE)
        self.assertEqual(-Sign.NEG, Sign.YES)
        self.assertEqual(-NONPOSITIVE, NATURAL)
        self.assertEqual(-NONZERO, NONZERO)
        self.assertEqual(-Sign.YES, Sign.NEG)
        self.assertEqual(-Sign.TOP, Sign.TOP)
        self.assertEqual(-Sign.NO, Sign.NO)

    def test_min(self):
        self.assertEqual(Sign.YES.Min(Sign.YES), Sign.YES)
        self.assertEqual(Sign.YES.Min(Sign.NO), Sign.NO)
        self.assertEqual(Sign.YES.Min(Sign.NEG), Sign.NEG)
        self.assertEqual(Sign.NEG.Min(Sign.YES), Sign.NEG)
        self.assertEqual(Sign.NEG.Min(Sign.NEG), Sign.NEG)
        self.assertEqual(Sign.NEG.Min(Sign.NO), Sign.NEG)
        self.assertEqual(Sign.NO.Min(Sign.NO), Sign.NO)

    def test_max(self):
        self.assertEqual(Sign.YES.Max(Sign.YES), Sign.YES)
        self.assertEqual(Sign.YES.Max(Sign.NO), Sign.YES)
        self.assertEqual(Sign.YES.Max(Sign.NEG), Sign.YES)
        self.assertEqual(Sign.NEG.Max(Sign.YES), Sign.YES)
        self.assertEqual(Sign.NEG.Max(Sign.NEG), Sign.NEG)
        self.assertEqual(Sign.NEG.Max(Sign.NO), Sign.NO)
        self.assertEqual(Sign.NO.Max(Sign.NO), Sign.NO)
