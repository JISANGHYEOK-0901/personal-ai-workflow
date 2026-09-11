import unittest
from average import average

class ExistingBehavior(unittest.TestCase):
    def test_nonempty(self):
        for values, expected in [([2, 4], 3), ([-4, -2], -3), ([7], 7)]:
            with self.subTest(values=values):
                self.assertEqual(average(values), expected)

if __name__ == '__main__':
    unittest.main()
