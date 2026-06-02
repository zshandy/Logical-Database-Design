import ijson
import sys

lengths = []
with open('outputs/20260327_135935/processed_prompts.json', 'rb') as f:
    for item in ijson.items(f, 'item'):
        lengths.append(len(item.get('input_seq', '')))

print(f'Total prompts: {len(lengths)}')
print(f'Min: {min(lengths)} chars (~{min(lengths)//4} tokens)')
print(f'Max: {max(lengths)} chars (~{max(lengths)//4} tokens)')
print(f'Avg: {sum(lengths)//len(lengths)} chars (~{sum(lengths)//len(lengths)//4} tokens)')
print(f'Median: {sorted(lengths)[len(lengths)//2]} chars (~{sorted(lengths)[len(lengths)//2]//4} tokens)')

for limit in [3072, 4096, 6144, 8192, 16384]:
    char_limit = limit * 4
    over = sum(1 for l in lengths if l > char_limit)
    print(f'Over ~{limit} tokens: {over}/{len(lengths)} ({over*100//len(lengths)}%)')
