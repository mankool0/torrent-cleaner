"""Discord webhook notifications."""

import requests
import logging
from typing import Dict
from datetime import datetime

from src.models import WorkflowStats


class DiscordNotifier:
    """Send notifications to Discord via webhook."""

    def __init__(self, webhook_url: str):
        """
        Initialize Discord notifier.

        Args:
            webhook_url: Discord webhook URL
        """
        self.webhook_url = webhook_url
        self.logger = logging.getLogger(__name__)
        self.enabled = bool(webhook_url)

        if not self.enabled:
            self.logger.info("Discord notifications disabled (no webhook URL)")

    def send_summary(self, summary: WorkflowStats, dry_run: bool = True) -> bool:
        """
        Send run summary to Discord.

        Args:
            summary: WorkflowStats with run statistics
            dry_run: Whether this was a dry run

        Returns:
            True if notification sent successfully
        """
        if not self.enabled:
            self.logger.debug("Discord notifications disabled, skipping")
            return True

        try:
            embed = self._build_summary_embed(summary, dry_run)

            payload = {
                'embeds': [embed]
            }

            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10
            )
            response.raise_for_status()

            self.logger.info("Discord notification sent successfully")
            return True

        except requests.RequestException as e:
            self.logger.error(f"Failed to send Discord notification: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error sending Discord notification: {e}")
            return False

    def _build_summary_embed(self, summary: WorkflowStats, dry_run: bool) -> Dict:
        """
        Build Discord embed for run summary.

        Args:
            summary: Run summary statistics
            dry_run: Whether this was a dry run

        Returns:
            Discord embed dictionary
        """
        if summary.torrents_deleted == 0:
            color = 0x00FF00  # Green
        elif dry_run:
            color = 0xFFFF00  # Yellow
        else:
            color = 0xFF0000  # Red

        mode = "[DRY RUN] " if dry_run else ""
        title = f"{mode}Torrent Cleaner Summary"

        description = f"Run completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        fields = [
            {
                'name': 'Torrents Processed',
                'value': str(summary.torrents_processed),
                'inline': True
            },
            {
                'name': 'Torrents Deleted',
                'value': str(summary.torrents_deleted),
                'inline': True
            },
            {
                'name': 'Torrents Kept',
                'value': str(summary.torrents_kept),
                'inline': True
            },
        ]

        if summary.hardlinks_fixed > 0 or summary.hardlinks_attempted > 0:
            fields.extend([
                {
                    'name': 'Hardlinks Fixed',
                    'value': str(summary.hardlinks_fixed),
                    'inline': True
                },
                {
                    'name': 'Hardlinks Failed',
                    'value': str(summary.hardlinks_failed),
                    'inline': True
                },
            ])

        fields.extend([
            {
                'name': 'Orphaned Files Found',
                'value': str(summary.orphaned_files_found),
                'inline': True
            },
        ])

        space_freed_gb = (summary.space_freed_dead_tracker_bytes + summary.space_freed_criteria_bytes) / (1024**3)
        space_hardlinks_gb = summary.space_saved_hardlinks_bytes / (1024**3)
        space_total_gb = space_freed_gb + space_hardlinks_gb
        if space_total_gb > 0:
            space_parts = []
            if summary.space_freed_dead_tracker_bytes > 0:
                space_parts.append(f"Dead trackers: {summary.space_freed_dead_tracker_bytes / (1024**3):.2f} GB")
            if summary.space_freed_criteria_bytes > 0:
                space_parts.append(f"Criteria: {summary.space_freed_criteria_bytes / (1024**3):.2f} GB")
            if space_hardlinks_gb > 0:
                space_parts.append(f"Hardlinks: {space_hardlinks_gb:.2f} GB")
            space_value = f"{space_total_gb:.2f} GB"
            if len(space_parts) > 1:
                space_value += f"\n({', '.join(space_parts)})"
            fields.append({
                'name': 'Space Saved',
                'value': space_value,
                'inline': True
            })

        if summary.deletion_reasons:
            reasons_text = '\n'.join([
                f"• {reason}: {count}"
                for reason, count in summary.deletion_reasons.items()
            ])
            fields.append({
                'name': 'Deletion Reasons',
                'value': reasons_text,
                'inline': False
            })

        if summary.deleted_torrents:
            torrents_list = summary.deleted_torrents[:5]
            torrents_text = '\n'.join([f"• {t}" for t in torrents_list])
            if len(summary.deleted_torrents) > 5:
                torrents_text += f"\n... and {len(summary.deleted_torrents) - 5} more"

            fields.append({
                'name': 'Deleted Torrents',
                'value': torrents_text,
                'inline': False
            })

        embed = {
            'title': title,
            'description': description,
            'color': color,
            'fields': fields,
            'timestamp': datetime.now().isoformat(),
            'footer': {
                'text': 'Torrent Cleaner'
            }
        }

        return embed

    def send_error(self, error_message: str) -> bool:
        """
        Send error notification to Discord.

        Args:
            error_message: Error message to send

        Returns:
            True if notification sent successfully
        """
        if not self.enabled:
            return True

        try:
            embed = {
                'title': 'Torrent Cleaner Error',
                'description': error_message,
                'color': 0xFF0000,  # Red
                'timestamp': datetime.now().isoformat()
            }

            payload = {'embeds': [embed]}

            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10
            )
            response.raise_for_status()

            self.logger.info("Discord error notification sent successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send Discord error notification: {e}")
            return False
