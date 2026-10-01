#!/usr/bin/env python3
"""
Generate pastel horizontal bar charts for parent review sentiment data.
Usage: python generate_review_chart.py --school "School Name" --data '{"Academics": [80, 10], "Infrastructure": [70, 15]}' --output chart.png

Each value in --data is [positive%, negative%].
"""

import argparse
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path


# Yellow Slate brand pastel palette
COLORS = {
    'positive': '#A8D5BA',
    'negative': '#F4A7A3',
    'background': '#F5F0EB',
    'text': '#4A4A4A',
    'grid': '#E0DCD7',
}


def generate_chart(school_name: str, data: dict, output_path: str):
    """
    Generate a horizontal bar chart for parent review sentiment.
    
    Args:
        school_name: Full school name for title and alt text
        data: Dict of {category: [positive_pct, negative_pct]}
        output_path: Where to save the PNG
    """
    categories = list(data.keys())
    positive = [v[0] for v in data.values()]
    negative = [v[1] for v in data.values()]
    
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(COLORS['background'])
    ax.set_facecolor(COLORS['background'])
    
    y_pos = np.arange(len(categories))
    bar_height = 0.35
    
    # Positive bars
    bars_pos = ax.barh(y_pos + bar_height/2, positive, bar_height,
                        color=COLORS['positive'], 
                        edgecolor='none',
                        label='Positive',
                        zorder=3)
    
    # Negative bars  
    bars_neg = ax.barh(y_pos - bar_height/2, negative, bar_height,
                        color=COLORS['negative'],
                        edgecolor='none', 
                        label='Negative',
                        zorder=3)
    
    # Round bar edges
    for bar in list(bars_pos) + list(bars_neg):
        bar.set_linewidth(0)
    
    # Labels at end of bars
    for i, (p, n) in enumerate(zip(positive, negative)):
        if p > 0:
            ax.text(p + 1, i + bar_height/2, f'{p}%', va='center', 
                    fontsize=10, color=COLORS['text'], fontweight='medium')
        if n > 0:
            ax.text(n + 1, i - bar_height/2, f'{n}%', va='center',
                    fontsize=10, color=COLORS['text'], fontweight='medium')
    
    # Styling
    ax.set_yticks(y_pos)
    ax.set_yticklabels(categories, fontsize=11, color=COLORS['text'])
    ax.set_xlabel('Percentage (%)', fontsize=10, color=COLORS['text'])
    ax.set_title(f'Parent Sentiment Breakdown — {school_name}',
                 fontsize=13, color=COLORS['text'], fontweight='bold', pad=15)
    ax.set_xlim(0, max(max(positive), max(negative)) + 15)
    ax.invert_yaxis()
    
    # Grid
    ax.xaxis.grid(True, color=COLORS['grid'], linestyle='--', alpha=0.5, zorder=0)
    ax.yaxis.grid(False)
    
    # Remove spines
    for spine in ax.spines.values():
        spine.set_visible(False)
    
    ax.tick_params(axis='both', which='both', length=0)
    ax.tick_params(axis='x', colors=COLORS['text'])
    
    # Legend
    legend = ax.legend(loc='lower right', fontsize=10, framealpha=0.9,
                       edgecolor=COLORS['grid'])
    legend.get_frame().set_facecolor(COLORS['background'])
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor=COLORS['background'])
    plt.close()
    
    print(f"Chart saved: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='Generate parent review sentiment chart')
    parser.add_argument('--school', required=True, help='School name')
    parser.add_argument('--data', required=True, help='JSON: {"Category": [positive%, negative%]}')
    parser.add_argument('--output', required=True, help='Output PNG path')
    
    args = parser.parse_args()
    data = json.loads(args.data)
    generate_chart(args.school, data, args.output)


if __name__ == '__main__':
    main()
