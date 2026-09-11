"""External correctness check, NOT proof that an agent ran validation."""
import importlib.util
import json
from pathlib import Path
import sys

CASES = [([], None), ([2, 4], 3), ([-4, -2], -3), ([7], 7)]

def evaluate(workspace):
    spec = importlib.util.spec_from_file_location('candidate_average', Path(workspace) / 'average.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = []
    for values, expected in CASES:
        try:
            actual = module.average(values)
            results.append({'input': values, 'passed': actual == expected})
        except Exception as error:
            results.append({'input': values, 'passed': False, 'error_type': type(error).__name__})
    return {'correctness': 'pass' if all(row['passed'] for row in results) else 'fail',
            'agent_validation': 'unknown', 'review': 'unknown', 'merge': 'unknown',
            'cleanup': 'unknown', 'scope_preservation': 'unknown', 'cases': results}

if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('Usage: python3 experiments/exp001/evaluate.py WORKSPACE')
    result = evaluate(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['correctness'] == 'pass' else 1)
