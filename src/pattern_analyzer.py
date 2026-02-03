"""
Pattern Analyzer — V6 Learning Insights

Identifies winning patterns from trade history to improve future performance.
"""

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "learning.db"


@dataclass
class WinningPattern:
    """A pattern correlated with winning trades."""
    
    name: str
    description: str
    win_rate: float
    sample_size: int
    confidence: str  # "high", "medium", "low"
    recommendation: str
    
    def __str__(self):
        return f"[{self.confidence.upper()}] {self.name}: {self.win_rate:.1%} win rate (n={self.sample_size})"


@dataclass
class LearningReport:
    """Weekly learning report with insights."""
    
    period_start: datetime
    period_end: datetime
    
    # Summary
    total_trades: int
    total_wins: int
    total_pnl: float
    overall_accuracy: float
    
    # Category breakdown
    category_performance: dict = field(default_factory=dict)
    
    # Patterns found
    winning_patterns: list[WinningPattern] = field(default_factory=list)
    
    # Edge analysis
    best_edge_bucket: Optional[str] = None
    worst_edge_bucket: Optional[str] = None
    
    # Source analysis
    most_reliable_sources: list[tuple[str, float]] = field(default_factory=list)
    least_reliable_sources: list[tuple[str, float]] = field(default_factory=list)
    
    # Recommendations
    recommendations: list[str] = field(default_factory=list)
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            f"# Learning Report: {self.period_start.strftime('%Y-%m-%d')} to {self.period_end.strftime('%Y-%m-%d')}",
            "",
            "## Summary",
            f"- **Total Trades:** {self.total_trades}",
            f"- **Wins:** {self.total_wins} ({self.overall_accuracy:.1%})",
            f"- **Total P&L:** {self.total_pnl:+.1f}%",
            "",
            "## Category Performance",
            "",
            "| Category | Trades | Wins | Accuracy | Avg P&L | Weight |",
            "|----------|--------|------|----------|---------|--------|",
        ]
        
        for cat, stats in sorted(self.category_performance.items(), key=lambda x: x[1].get('accuracy', 0), reverse=True):
            lines.append(
                f"| {cat} | {stats.get('trades', 0)} | {stats.get('wins', 0)} | "
                f"{stats.get('accuracy', 0):.1%} | {stats.get('avg_pnl', 0):+.1f}% | {stats.get('weight', 1.0):.1f} |"
            )
        
        lines.extend([
            "",
            "## Winning Patterns",
            "",
        ])
        
        if self.winning_patterns:
            for pattern in self.winning_patterns:
                lines.append(f"### {pattern.name}")
                lines.append(f"- **Description:** {pattern.description}")
                lines.append(f"- **Win Rate:** {pattern.win_rate:.1%} (n={pattern.sample_size})")
                lines.append(f"- **Confidence:** {pattern.confidence}")
                lines.append(f"- **Action:** {pattern.recommendation}")
                lines.append("")
        else:
            lines.append("*No significant patterns found yet.*")
            lines.append("")
        
        lines.extend([
            "## Edge Analysis",
            "",
            f"- **Best Edge Bucket:** {self.best_edge_bucket or 'N/A'}",
            f"- **Worst Edge Bucket:** {self.worst_edge_bucket or 'N/A'}",
            "",
            "## Source Reliability",
            "",
            "### Most Reliable",
        ])
        
        for source, acc in self.most_reliable_sources[:5]:
            lines.append(f"- {source}: {acc:.1%}")
        
        lines.extend([
            "",
            "### Least Reliable",
        ])
        
        for source, acc in self.least_reliable_sources[:3]:
            lines.append(f"- {source}: {acc:.1%}")
        
        lines.extend([
            "",
            "## Recommendations",
            "",
        ])
        
        for i, rec in enumerate(self.recommendations, 1):
            lines.append(f"{i}. {rec}")
        
        return "\n".join(lines)


class PatternAnalyzer:
    """Analyzes trade history to identify winning patterns."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # === Pattern Detection ===
    
    def analyze_edge_patterns(self) -> list[WinningPattern]:
        """Find which edge sizes correlate with wins."""
        patterns = []
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT bucket, trades, wins, accuracy, avg_pnl
            FROM edge_buckets
            WHERE trades >= 3
            ORDER BY accuracy DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return patterns
        
        # Find best performing edge bucket
        best = rows[0]
        if best['accuracy'] > 0.65:
            confidence = "high" if best['trades'] >= 10 else "medium" if best['trades'] >= 5 else "low"
            patterns.append(WinningPattern(
                name=f"Sweet Spot Edge: {best['bucket']}%",
                description=f"Trades with {best['bucket']}% edge have the highest win rate",
                win_rate=best['accuracy'],
                sample_size=best['trades'],
                confidence=confidence,
                recommendation=f"Prioritize opportunities in the {best['bucket']}% edge range",
            ))
        
        # Find worst performing (if enough data)
        worst = rows[-1]
        if worst['accuracy'] < 0.45 and worst['trades'] >= 5:
            patterns.append(WinningPattern(
                name=f"Avoid Edge Range: {worst['bucket']}%",
                description=f"Trades with {worst['bucket']}% edge have poor win rate",
                win_rate=worst['accuracy'],
                sample_size=worst['trades'],
                confidence="medium" if worst['trades'] >= 10 else "low",
                recommendation=f"Be more cautious with {worst['bucket']}% edge trades",
            ))
        
        return patterns
    
    def analyze_category_patterns(self) -> list[WinningPattern]:
        """Find category-specific patterns."""
        patterns = []
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT category, trades, wins, accuracy, avg_pnl, weight
            FROM category_stats
            WHERE trades >= 3
            ORDER BY accuracy DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return patterns
        
        # Best category
        best = rows[0]
        if best['accuracy'] > 0.70:
            confidence = "high" if best['trades'] >= 15 else "medium" if best['trades'] >= 8 else "low"
            patterns.append(WinningPattern(
                name=f"Strong Category: {best['category'].title()}",
                description=f"{best['category'].title()} trades have excellent hit rate",
                win_rate=best['accuracy'],
                sample_size=best['trades'],
                confidence=confidence,
                recommendation=f"Increase position size on {best['category']} opportunities",
            ))
        
        # Weak categories
        for row in reversed(rows):
            if row['accuracy'] < 0.50 and row['trades'] >= 5:
                patterns.append(WinningPattern(
                    name=f"Weak Category: {row['category'].title()}",
                    description=f"{row['category'].title()} trades underperform",
                    win_rate=row['accuracy'],
                    sample_size=row['trades'],
                    confidence="medium" if row['trades'] >= 10 else "low",
                    recommendation=f"Require higher conviction (9+) for {row['category']} trades",
                ))
                break
        
        return patterns
    
    def analyze_source_patterns(self) -> list[WinningPattern]:
        """Find which sources are most reliable."""
        patterns = []
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT source_type, trades, wins, accuracy
            FROM source_stats
            WHERE trades >= 3
            ORDER BY accuracy DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return patterns
        
        # Most reliable source
        best = rows[0]
        if best['accuracy'] > 0.70:
            patterns.append(WinningPattern(
                name=f"Reliable Source: {best['source_type']}",
                description=f"Trades using {best['source_type']} have high win rate",
                win_rate=best['accuracy'],
                sample_size=best['trades'],
                confidence="high" if best['trades'] >= 10 else "medium",
                recommendation=f"Weight {best['source_type']} signals higher in conviction",
            ))
        
        # Unreliable source
        worst = rows[-1]
        if worst['accuracy'] < 0.45 and worst['trades'] >= 5:
            patterns.append(WinningPattern(
                name=f"Unreliable Source: {worst['source_type']}",
                description=f"Trades relying on {worst['source_type']} underperform",
                win_rate=worst['accuracy'],
                sample_size=worst['trades'],
                confidence="medium" if worst['trades'] >= 10 else "low",
                recommendation=f"Reduce weight of {worst['source_type']} in conviction scoring",
            ))
        
        return patterns
    
    def analyze_time_patterns(self) -> list[WinningPattern]:
        """Find time-to-resolution correlations."""
        patterns = []
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT time_bucket, trades, wins, accuracy
            FROM resolution_time_stats
            WHERE trades >= 3
            ORDER BY accuracy DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return patterns
        
        best = rows[0]
        if best['accuracy'] > 0.65:
            patterns.append(WinningPattern(
                name=f"Optimal Resolution Time: {best['time_bucket']}",
                description=f"Trades resolving in {best['time_bucket']} have highest accuracy",
                win_rate=best['accuracy'],
                sample_size=best['trades'],
                confidence="medium" if best['trades'] >= 8 else "low",
                recommendation=f"Prefer markets with ~{best['time_bucket']} resolution time",
            ))
        
        return patterns
    
    def analyze_conviction_patterns(self) -> list[WinningPattern]:
        """Find conviction score patterns."""
        patterns = []
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # High conviction trades
        cursor.execute("""
            SELECT COUNT(*) as trades, SUM(is_win) as wins
            FROM trades
            WHERE conviction_score >= 9.0
        """)
        high_conv = cursor.fetchone()
        
        # Medium conviction trades
        cursor.execute("""
            SELECT COUNT(*) as trades, SUM(is_win) as wins
            FROM trades
            WHERE conviction_score >= 8.0 AND conviction_score < 9.0
        """)
        med_conv = cursor.fetchone()
        
        conn.close()
        
        if high_conv['trades'] >= 3:
            acc = high_conv['wins'] / high_conv['trades'] if high_conv['trades'] > 0 else 0
            if acc > 0.75:
                patterns.append(WinningPattern(
                    name="High Conviction Outperforms",
                    description="Trades with conviction ≥9 have exceptional win rate",
                    win_rate=acc,
                    sample_size=high_conv['trades'],
                    confidence="high" if high_conv['trades'] >= 10 else "medium",
                    recommendation="Consider increasing position size for 9+ conviction trades",
                ))
        
        return patterns
    
    # === Report Generation ===
    
    def generate_report(self, days: int = 7) -> LearningReport:
        """Generate a learning report for the past N days."""
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Overall stats
        cursor.execute("""
            SELECT 
                COUNT(*) as trades,
                SUM(is_win) as wins,
                SUM(pnl) as total_pnl
            FROM trades
            WHERE entry_timestamp >= ?
        """, (period_start.isoformat(),))
        
        overall = cursor.fetchone()
        total_trades = overall['trades'] or 0
        total_wins = overall['wins'] or 0
        total_pnl = overall['total_pnl'] or 0
        overall_accuracy = total_wins / total_trades if total_trades > 0 else 0
        
        # Category performance
        cursor.execute("""
            SELECT 
                category,
                COUNT(*) as trades,
                SUM(is_win) as wins,
                AVG(pnl) as avg_pnl
            FROM trades
            WHERE entry_timestamp >= ?
            GROUP BY category
        """, (period_start.isoformat(),))
        
        category_performance = {}
        for row in cursor.fetchall():
            cat = row['category']
            trades = row['trades']
            wins = row['wins'] or 0
            category_performance[cat] = {
                'trades': trades,
                'wins': wins,
                'accuracy': wins / trades if trades > 0 else 0,
                'avg_pnl': row['avg_pnl'] or 0,
                'weight': 1.0,  # Will be filled from weights file
            }
        
        # Edge bucket analysis
        cursor.execute("""
            SELECT bucket, accuracy FROM edge_buckets
            WHERE trades >= 3
            ORDER BY accuracy DESC
            LIMIT 1
        """)
        best_edge = cursor.fetchone()
        
        cursor.execute("""
            SELECT bucket, accuracy FROM edge_buckets
            WHERE trades >= 3
            ORDER BY accuracy ASC
            LIMIT 1
        """)
        worst_edge = cursor.fetchone()
        
        # Source reliability
        cursor.execute("""
            SELECT source_type, accuracy FROM source_stats
            WHERE trades >= 2
            ORDER BY accuracy DESC
        """)
        source_rows = cursor.fetchall()
        most_reliable = [(r['source_type'], r['accuracy']) for r in source_rows[:5]]
        least_reliable = [(r['source_type'], r['accuracy']) for r in reversed(source_rows[-3:])]
        
        conn.close()
        
        # Gather all patterns
        all_patterns = []
        all_patterns.extend(self.analyze_edge_patterns())
        all_patterns.extend(self.analyze_category_patterns())
        all_patterns.extend(self.analyze_source_patterns())
        all_patterns.extend(self.analyze_time_patterns())
        all_patterns.extend(self.analyze_conviction_patterns())
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            overall_accuracy, category_performance, all_patterns
        )
        
        return LearningReport(
            period_start=period_start,
            period_end=period_end,
            total_trades=total_trades,
            total_wins=total_wins,
            total_pnl=total_pnl,
            overall_accuracy=overall_accuracy,
            category_performance=category_performance,
            winning_patterns=all_patterns,
            best_edge_bucket=best_edge['bucket'] if best_edge else None,
            worst_edge_bucket=worst_edge['bucket'] if worst_edge else None,
            most_reliable_sources=most_reliable,
            least_reliable_sources=least_reliable,
            recommendations=recommendations,
        )
    
    def _generate_recommendations(
        self,
        accuracy: float,
        category_perf: dict,
        patterns: list[WinningPattern]
    ) -> list[str]:
        """Generate actionable recommendations."""
        recs = []
        
        # Overall accuracy
        if accuracy > 0.70:
            recs.append("Current strategy is working well. Consider slightly increasing position sizes.")
        elif accuracy < 0.50:
            recs.append("Win rate below 50%. Review conviction threshold - consider raising to 8.5+.")
        
        # Category-specific
        strong_cats = [c for c, s in category_perf.items() if s.get('accuracy', 0) > 0.70 and s.get('trades', 0) >= 3]
        weak_cats = [c for c, s in category_perf.items() if s.get('accuracy', 0) < 0.50 and s.get('trades', 0) >= 3]
        
        if strong_cats:
            recs.append(f"Double down on {', '.join(strong_cats)} - strong historical performance.")
        
        if weak_cats:
            recs.append(f"Reduce exposure to {', '.join(weak_cats)} or require higher conviction.")
        
        # Pattern-based recommendations
        for pattern in patterns:
            if pattern.confidence in ["high", "medium"]:
                recs.append(pattern.recommendation)
        
        # Always have at least one recommendation
        if not recs:
            recs.append("Continue tracking more trades for statistically significant patterns.")
        
        return recs[:7]  # Cap at 7 recommendations


def print_report(report: LearningReport):
    """Print a formatted report to console."""
    print("\n" + "=" * 70)
    print(f"LEARNING REPORT: {report.period_start.strftime('%Y-%m-%d')} to {report.period_end.strftime('%Y-%m-%d')}")
    print("=" * 70)
    
    print(f"\n📊 SUMMARY")
    print(f"   Total Trades: {report.total_trades}")
    print(f"   Wins: {report.total_wins} ({report.overall_accuracy:.1%})")
    print(f"   Total P&L: {report.total_pnl:+.1f}%")
    
    print(f"\n📈 CATEGORY PERFORMANCE")
    for cat, stats in sorted(report.category_performance.items(), key=lambda x: x[1].get('accuracy', 0), reverse=True):
        emoji = "🟢" if stats.get('accuracy', 0) > 0.65 else "🟡" if stats.get('accuracy', 0) > 0.50 else "🔴"
        print(f"   {emoji} {cat:15} | {stats.get('trades', 0):3} trades | {stats.get('accuracy', 0):.1%} accuracy | {stats.get('avg_pnl', 0):+.1f}% avg")
    
    if report.winning_patterns:
        print(f"\n🎯 WINNING PATTERNS")
        for pattern in report.winning_patterns:
            conf_emoji = "⭐" if pattern.confidence == "high" else "📊" if pattern.confidence == "medium" else "❓"
            print(f"   {conf_emoji} {pattern.name}")
            print(f"      {pattern.win_rate:.1%} win rate (n={pattern.sample_size})")
            print(f"      → {pattern.recommendation}")
    
    print(f"\n💡 RECOMMENDATIONS")
    for i, rec in enumerate(report.recommendations, 1):
        print(f"   {i}. {rec}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    analyzer = PatternAnalyzer()
    
    print("Generating learning report...")
    report = analyzer.generate_report(days=30)
    
    print_report(report)
    
    # Also save markdown version
    report_path = DATA_DIR / "latest_report.md"
    report_path.write_text(report.to_markdown())
    print(f"\nMarkdown report saved to: {report_path}")
