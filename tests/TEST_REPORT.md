# Test Report

Date: 2026-10-02 · Python 3.12.3 · macOS (Darwin 23.1.0)

## 1. Tests and what they check

| Test | What it checks |
|---|---|
| `test_home_page_is_public` | The home page loads (200) without logging in. |
| `test_dashboard_requires_login[...]` | The grid page, grid fragment, agent page and activity fragment return 401 with no credentials and ask for a login. |
| `test_dashboard_rejects_wrong_password[...]` | The same pages return 401 with a wrong password. |
| `test_dashboard_allows_correct_login[...]` | The same pages return 200 with the right username and password. |
| `test_dashboard_actions_require_login[...]` | Every dashboard action (add agent, command, rename, add/remove tag, delete agent, view/replace key, pin, bell, monitor, monitor pin, create/rename/delete folder) returns 401 without a login and changes nothing. |
| `test_dashboard_denied_when_password_env_is_empty` | An empty `DASHBOARD_PASSWORD` can't be matched by an empty password. |
| `test_unknown_agent_and_folder_return_404` | An agent or folder that doesn't exist returns 404. |
| `test_api_requires_key[...]` | The `/api/*` routes (events, commands, outputs, monitor) return 401 with no `X-API-Key` header. |
| `test_api_rejects_wrong_key[...]` | All three `/api/*` routes return 401 with a key that belongs to no agent. |
| `test_api_rejects_empty_key[...]` | An empty `X-API-Key` header is rejected (401). |
| `test_api_rejects_every_key_when_there_are_no_agents[...]` | With no agents at all, even an empty header is rejected. |
| `test_key_is_stored_as_fingerprint_and_encrypted_copy` | The database stores the key's SHA-256 fingerprint and an encrypted copy, never the plain key, and the copy decrypts back to the key. |
| `test_add_agent_with_own_key` | An agent added with a key you typed can use the API, and its "last seen" time is recorded. |
| `test_add_agent_generates_key_when_left_blank` | Leaving the key blank generates one, shows it, and that key works for the API. |
| `test_add_agent_rejects_bad_input[...]` | An empty or too-long name, a key under 20 characters, or a key with spaces is refused, and no agent is created. |
| `test_add_agent_rejects_duplicate_name_and_key` | A name or key that's already in use is refused. |
| `test_add_agent_inside_folder_tags_it` | Adding an agent while a folder is open puts it in that folder. |
| `test_round_trip_between_agent_and_dashboard` | Full round trip: an event shows on the card and in the activity log; a message sent from the agent's page shows up as pending for that agent; PATCH marks it done. |
| `test_commands_only_go_to_their_own_agent` | A command for one agent isn't given to another. |
| `test_agent_cannot_update_another_agents_command` | An agent can't mark another agent's command as done (404). |
| `test_events_only_show_on_their_own_agent` | One agent's events don't appear in another agent's activity log. |
| `test_pending_commands_are_oldest_first` | An agent's pending commands come back oldest first. |
| `test_empty_message_is_not_saved` | Sending a blank message shows a warning and saves nothing. |
| `test_events_empty_state` | An agent with no events shows a friendly empty message. |
| `test_patch_missing_command_returns_404` | PATCH on a command that doesn't exist returns 404. |
| `test_rename_keeps_the_agent_connected` | Renaming changes the name on the grid, and the agent's key still works for the same agent. |
| `test_rename_rejects_taken_or_empty_names` | Renaming to a name that's taken, or to a blank name, is refused, and the old name stays. |
| `test_create_folder_shows_in_sidebar` | Creating a folder opens it and lists it in the sidebar. |
| `test_duplicate_folder_name_shows_error` | A second folder with the same name is refused with a message. |
| `test_folder_grid_shows_only_tagged_agents` | A folder's grid shows only its agents; All Agents shows everyone. |
| `test_add_and_remove_tag` | Adding a tag puts the agent in the folder, and the tag's × takes it out. |
| `test_adding_same_tag_twice_is_harmless` | Tagging an agent with the same folder twice doesn't create a duplicate. |
| `test_rename_folder` | A folder can be renamed. |
| `test_delete_folder_keeps_its_agents` | Deleting a folder removes the folder and its tags but keeps the agents. |
| `test_delete_agent_needs_the_edit_password` | A wrong agent editing password deletes nothing and shows an error. |
| `test_delete_agent_denied_when_edit_password_env_is_empty` | With no `AGENT_EDIT_PASSWORD` set, nothing can be deleted, even with an empty password. |
| `test_delete_agent_removes_everything_it_owns` | The right password deletes the agent, its events, commands and tags (the folder stays), and its key stops working. |
| `test_agent_settings_hold_name_tags_key_and_delete` | The agent page shows the name, a gear button and the folder tags as plain labels, with no editing controls. Rename, add/remove tag, View key, Replace key, Delete agent and the password boxes are all inside the settings pop-up. |
| `test_agent_settings_start_closed` | The settings pop-up is closed when the page loads. |
| `test_settings_stay_open_after_rename_or_tag_change` | After renaming, adding or removing a tag, the refreshed section keeps settings open, both in Alpine's state and in the HTML class (HTMX restores the received class after a swap). |
| `test_dashboard_actions_need_csrf_token[...]` | Every dashboard action is refused (403) without the CSRF token, even when logged in, and nothing changes. |
| `test_dashboard_actions_reject_wrong_csrf_token[...]` | Every dashboard action is refused (403) with a wrong CSRF token. |
| `test_csrf_token_in_hidden_form_field_works` | Plain HTML forms can send the token as a hidden `csrf_token` field. |
| `test_csrf_token_only_on_pages_behind_login` | The token appears on dashboard pages but not on the public home page. |
| `test_csrf_token_changes_with_the_password` | Changing `DASHBOARD_PASSWORD` changes the token. |
| `test_view_key_needs_the_edit_password` | View key with a wrong password shows an error and not the key. |
| `test_view_key_shows_the_key` | View key with the right password shows the key, and tells the browser not to cache it. |
| `test_view_key_for_agent_without_stored_copy` | An agent with no encrypted copy gets a "use Replace key" message. |
| `test_view_key_when_encryption_secret_changed` | If `KEY_ENCRYPTION_SECRET` changed, View key explains it can't decrypt and shows nothing. |
| `test_replace_key_needs_the_edit_password` | Replace key with a wrong password changes nothing, and the old key still works. |
| `test_replace_key_generates_new_key_and_old_one_stops_working` | Replacing makes a new key that works for the same agent; the old key gets 401, and View key shows the new one. |
| `test_replace_key_with_own_key` | A key you type can be used as the replacement. |
| `test_replace_key_rejects_bad_or_used_keys` | A replacement key that's too short, or already used by another agent, is refused and nothing changes. |
| `test_keys_need_the_encryption_secret` | With no `KEY_ENCRYPTION_SECRET`, adding an agent is refused with a clear message. |
| `test_sidebar_has_fold_button_info_and_connector` | The dashboard has the fold-away button, the "How this dashboard works" window, and the Implement connector links. |
| `test_connector_downloads_require_login` | Both connector downloads need the dashboard login. |
| `test_connector_code_download` | The code download is named `dashboard_connector.py` and is valid Python with `report` and `listen`. The address and key are clearly marked `REPLACE THIS PLACEHOLDER` values, only a "downloaded from" hint is filled in, and no key is included. |
| `test_connector_prompt_download` | The prompt download tells the AI assistant to ask the user for the dashboard's address and the agent's key before coding. It covers local, Render and custom-domain addresses, and offers the downloaded-from address only as a suggestion. |
| `test_connector_hint_uses_forwarded_https_address[...]` | Behind an HTTPS proxy (Render or any other host, including a `https,http` list), the "downloaded from" hint shows `https://`. |
| `test_new_agent_shows_both_connection_values` | After adding an agent, the dashboard shows `DASHBOARD_URL` and `DASHBOARD_API_KEY` ready to copy. |
| `test_connector_reports_to_any_address` | The connector sends a report with the agent's key to a stand-in website on a random address, and tidies a trailing `/dashboard/`. |
| `test_connector_handles_commands_and_marks_them_done` | The connector passes a waiting command to the handler, then marks it done. |
| `test_connector_with_placeholders_does_nothing` | With the placeholders untouched and no environment variables, the connector prints a clear setup message and sends nothing. |
| `test_connector_explains_bad_settings[...]` | An address without `http(s)://`, or a missing or placeholder key, is explained. |
| `test_connector_warns_about_plain_http_on_remote_hosts` | Plain `http://` to a remote host warns that the key would travel unencrypted; local addresses don't warn. |
| `test_connector_does_not_follow_redirects` | A redirect (e.g. `http` to `https`) isn't followed, so a report can't be silently lost; the warning names the address to use. |
| `test_connector_explains_wrong_key` | A 401 prints a hint to check `DASHBOARD_API_KEY`. |
| `test_output_kinds[...]` | Text, numbers, links, lists/dicts and true/false are stored with the right kind. `javascript:` addresses and text that merely contains a link stay plain text. |
| `test_output_category_must_be_1_to_50_characters[...]` | Empty, blank or over-long categories are refused (422). |
| `test_output_content_cannot_be_empty_or_huge` | Empty content, or more than 20,000 characters, is refused. |
| `test_output_file_upload_and_download` | A PNG is stored, downloads byte-for-byte, is served inline with `nosniff`, and shows as an image on the page. |
| `test_non_image_files_are_only_downloads[...]` | PDF, SVG and HTML files are only offered as downloads (`attachment`, `application/octet-stream`), never shown inside the page. |
| `test_output_file_size_limit` | A file over 5 MB is refused (413) and nothing is saved. |
| `test_output_file_name_is_cleaned` | A file name like `../../etc/passwd` is stored as just `passwd`. |
| `test_output_file_download_needs_login_and_exists` | File downloads need the dashboard login. A missing file, or an output that isn't a file, returns 404. |
| `test_output_file_needs_api_key` | Uploading a file without an agent key is refused (401). |
| `test_outputs_only_show_on_their_own_agent` | One agent's outputs don't appear on another agent's page. |
| `test_output_links_are_clickable_and_safe` | Link outputs are clickable, open safely (`noopener noreferrer`), and can never be `javascript:` links. |
| `test_output_content_and_category_are_escaped` | HTML in an output or category name shows as text. |
| `test_pin_only_one_category_and_show_on_card` | Pinning shows that category's newest output on the grid card. Pinning another moves the pin; clicking the pinned one again unpins it. |
| `test_outputs_show_nothing_until_chosen` | With outputs available, the agent page shows none (not even All is ticked) and asks you to use Filter. With no outputs, it says so. |
| `test_pinned_category_starts_ticked` | The one exception: a pinned category starts ticked and its outputs show; others stay unticked. |
| `test_outputs_filter_by_ticked_categories` | One or several ticked categories, or All, decide what's shown; unknown categories are ignored. |
| `test_filter_button_summary` | The Filter button says "All", the one category's name, "2 categories" or "Choose...". |
| `test_outputs_sorting[...]` | Sorting by date, category name and content, each ascending and descending, gives the right order. |
| `test_unknown_sort_falls_back_to_newest_first` | Unknown sort options fall back to newest first. |
| `test_filter_rows_only_resent_when_categories_change` | The 3-second refresh only re-sends the Filter's category rows when a category was added, keeping what's ticked, so an open panel isn't disturbed. |
| `test_pin_and_bell_keep_what_is_ticked` | Pressing a pin or bell inside the Filter keeps the current ticks. |
| `test_agent_page_layout` | The page order is Monitor, Outputs, Activity. Controls appear as a sticky right-hand column and as a phone bottom bar. The Filter form holds the ticks and the sort. |
| `test_pinned_category_with_no_outputs_yet` | A pinned category with no outputs yet shows "Nothing yet." on the card. |
| `test_notify_toggle_is_saved` | The bell turns a category's notification setting on and off (saved for the future Discord bot). |
| `test_deleting_agent_deletes_its_outputs_and_files` | Deleting an agent also deletes its outputs, their files and its notification settings. |
| `test_agent_sets_and_clears_monitor` | `PUT /api/monitor` sets the link (shown with "Open" and "Show here") and clears it. |
| `test_monitor_must_be_http_or_https[...]` | `javascript:`, `ftp:` or bare addresses are refused, both from the API and from settings. |
| `test_user_sets_monitor_in_settings` | Setting the monitor in Agent settings keeps settings open, updates the Monitor section, and an empty link removes it. |
| `test_monitor_pdf_is_shown_inside_the_page` | A PDF monitor is embedded in the agent's page and served inline as `application/pdf` with `nosniff`. |
| `test_monitor_pdf_must_be_a_real_pdf` | A file that doesn't start with `%PDF-` (e.g. HTML pretending to be a PDF) is refused (422); over 5 MB is refused (413). |
| `test_monitor_pdf_needs_key_and_login` | Uploading needs the agent's key; viewing needs the dashboard login. |
| `test_only_the_latest_monitor_is_kept` | A new PDF replaces the old one (whose file is deleted), and a link replaces a PDF. |
| `test_monitor_section_only_refreshes_when_changed` | The Monitor's 10-second check gets "204 No Content" while nothing changed (so a PDF being read isn't reloaded), and the new section once it did. |
| `test_pin_monitor_shares_the_single_pin` | Pinning the Monitor unpins any category and shows the monitor on the grid card; pinning a category unpins the Monitor and updates its pin button; clicking again unpins. |
| `test_pinned_monitor_link_on_card` | A pinned monitor link shows on the grid card as a link. |
| `test_activity_logs_output_and_monitor_updates` | Each output (text, list/dict, file) and each monitor change (PDF, link, removed from the dashboard) adds a timestamped Activity line, shown with its own badge colour. |
| `test_long_output_is_shortened_in_activity` | Long outputs are shortened in their Activity line. |
| `test_deleting_agent_deletes_its_monitor_pdf` | Deleting an agent also deletes its monitor PDF. |
| `test_connector_set_monitor_with_pdf` | The connector's `set_monitor(Path("x.pdf"))` uploads the PDF with its label, and refuses non-PDF files before sending anything. |
| `test_pause_and_start_switch_the_paused_state` | Pause and Start set the paused state the connector reads; the page's badge updates straight away; the grid card shows "paused"; the agent still receives the command. |
| `test_check_in_keeps_agent_online` | The connector's check-in records the agent as seen, and needs the key. |
| `test_messages_are_off_until_the_agent_accepts_them` | Without the agent's "accepts messages" signal there's no working message box, and messages are refused. After the signal, the box appears (wide screens and phones) and messages go through. The signal can be turned off again. |
| `test_messages_ready_check` | The page's 5-second check gets "nothing changed" (204), or a page reload once the agent starts accepting messages. |
| `test_connector_holds_outputs_while_paused` | While paused, the connector holds outputs and monitor updates (sends nothing, even on `flush()`) but lets reports through. On Start, the held items are sent in order. |
| `test_connector_wait_if_paused` | `wait_if_paused()` returns at once when running, and waits until Start when paused. |
| `test_connector_start_pause_commands_update_state` | A Start/Pause command received by the connector updates `is_paused()` straight away and still reaches `on_command`. |
| `test_connector_accept_messages` | `accept_messages()` sends the "I accept messages" check-in, and messages arrive at its handler as text (not at `on_command`). |
| `test_messages_go_to_on_command_without_accept_messages` | Without a message handler, messages still reach `on_command`, as before. |
| `test_agent_declares_its_check_in_interval` | An agent's check-in can declare how often it checks in; the agent page shows it ("checks in every 1 h"). |
| `test_check_in_interval_must_be_sensible[...]` | Intervals under 1 second, over a week, or not a number are refused (422). |
| `test_online_follows_the_agents_own_rhythm[...]` | "Online" uses each agent's own interval plus slack: default 60 s, every 5 s, hourly and daily agents are each online or offline at the right times. |
| `test_check_in_interval_wording` | Intervals read naturally ("5 min", "1 h 30 min", "2 days"); undeclared ones show "(default)". |
| `test_missing_columns_are_added_to_an_existing_database` | A database made by an older version gets newly added columns at startup, keeping existing rows with sensible defaults; running it again changes nothing. |
| `test_connector_check_in_declares_interval_and_handles_commands` | `check_in(every=3600)` sends the interval, then picks up waiting commands. |
| `test_connector_check_in_without_handlers_only_checks_in` | Without handlers, `check_in()` only checks in and learns the pause state. |
| `test_connector_start_check_ins_runs_in_background` | `start_check_ins(every)` checks in in the background, declaring the interval. |
| `test_connector_out_of_range_interval_is_clamped_not_an_error` | An interval out of range is brought into range with a warning, never an error. |
| `test_output_keeps_its_original_time` | An output sent with an earlier `created_at` keeps that time, sits at its real place in the list, and its Activity line says "(delivered late)". |
| `test_future_times_become_now` | A `created_at` in the future (a wrong clock) is treated as now. |
| `test_late_file_output_and_report` | File outputs and reports also keep their original times; an unreadable time is refused (422). |
| `test_late_monitor_never_replaces_a_newer_one` | A late monitor link or PDF older than the current monitor is skipped (its PDF isn't kept), and the skip is noted in Activity. |
| `test_buffer_saves_and_later_sends_with_original_time` | When the dashboard answers 503, the output is saved; once it's back, `flush()` sends it with its original time. |
| `test_buffer_keeps_order` | Saved items are sent oldest first, and a new item queues behind waiting ones. |
| `test_buffer_survives_restart` | Items saved by one run are found and sent by the next run. |
| `test_buffer_when_dashboard_unreachable` | With nothing listening at the address, the output is saved with a message about the offline buffer. |
| `test_buffer_copies_files` | A file output is copied into the buffer, so it's still sent after the original is deleted; the copy is cleaned up afterwards. |
| `test_buffer_keeps_only_latest_monitor` | Only the newest pending monitor update is kept. |
| `test_mistakes_are_not_buffered` | 401, 404, 413 and 422 replies aren't saved, because retrying wouldn't help. |
| `test_buffer_has_a_size_limit` | When the buffer is full, the oldest items are dropped with a warning. |
| `test_connector_output_sends_content_and_category` | The connector's `output()` sends content and category, turning dates and other unusual values into text. |
| `test_connector_output_sends_files` | `output(Path(...), category)` uploads the file with its name and type. |
| `test_connector_output_skips_oversize_and_missing_files` | Files over 5 MB are skipped with a warning, and a missing file prints a warning instead of crashing. |
| `test_connector_set_monitor` | The connector's `set_monitor()` sends the link and label. |
| `test_connector_survives_unreachable_dashboard` | With nothing at the address, reporting and command checks print a warning instead of crashing. |
| `test_unknown_connector_format_returns_404` | Asking for a format other than code or prompt returns 404. |
| `test_empty_grid_shows_only_add_agent_card` | With no agents, the grid shows just the Add Agent card. |
| `test_grid_pages_hold_nine_cells_including_add_card` | 9 agents plus the Add Agent card make 10 cells: page 1 holds 9 agents, page 2 holds the Add Agent card. |
| `test_no_page_buttons_when_everything_fits` | With 8 agents and the Add Agent card (9 cells), there are no page buttons. |
| `test_folder_page_buttons_keep_the_folder` | Page buttons inside a folder stay in that folder. |
| `test_out_of_range_page_shows_last_page` | A page number past the end shows the last page instead of an error. |
| `test_grid_cell_has_only_start_and_pause` | Grid cards have only Start and Pause (no message box). |
| `test_online_offline_and_never_connected_badges` | Cards show "online", "offline" (silent for 5 minutes), or "never connected" correctly. |
| `test_event_message_html_is_escaped` | HTML in an event message is shown as text in both the activity log and the grid. |
| `test_agent_and_folder_names_are_escaped` | HTML in agent or folder names is shown as text on the grid, the agent page, and the folder page. |
| `test_command_alert_html_is_escaped` | HTML in a command name is escaped in the pop-up alert. |
| `test_database_url_conversion[...]` | `postgres://` and `postgresql://` become `postgresql+psycopg://`, and other URLs are left unchanged. |

## 2. `pytest -v` result

```text
tests/test_app.py::test_home_page_is_public PASSED
tests/test_app.py::test_dashboard_requires_login[/dashboard] PASSED
tests/test_app.py::test_dashboard_requires_login[/dashboard/grid] PASSED
tests/test_app.py::test_dashboard_requires_login[/dashboard/agents/{id}] PASSED
tests/test_app.py::test_dashboard_requires_login[/dashboard/agents/{id}/events] PASSED
tests/test_app.py::test_dashboard_rejects_wrong_password[/dashboard] PASSED
tests/test_app.py::test_dashboard_rejects_wrong_password[/dashboard/grid] PASSED
tests/test_app.py::test_dashboard_rejects_wrong_password[/dashboard/agents/{id}] PASSED
tests/test_app.py::test_dashboard_rejects_wrong_password[/dashboard/agents/{id}/events] PASSED
tests/test_app.py::test_dashboard_allows_correct_login[/dashboard] PASSED
tests/test_app.py::test_dashboard_allows_correct_login[/dashboard/grid] PASSED
tests/test_app.py::test_dashboard_allows_correct_login[/dashboard/agents/{id}] PASSED
tests/test_app.py::test_dashboard_allows_correct_login[/dashboard/agents/{id}/events] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents-data0] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/command-data1] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/rename-data2] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/tags-data3] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/tags/1/remove-data4] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/delete-data5] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/key/view-data6] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/key/replace-data7] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/outputs/pin-data8] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/outputs/notify-data9] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/monitor-data10] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/agents/{id}/monitor/pin-data11] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/folders-data12] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/folders/1/rename-data13] PASSED
tests/test_app.py::test_dashboard_actions_require_login[/dashboard/folders/1/delete-data14] PASSED
tests/test_app.py::test_dashboard_denied_when_password_env_is_empty PASSED
tests/test_app.py::test_unknown_agent_and_folder_return_404 PASSED
tests/test_app.py::test_api_requires_key[post-/api/events-body0] PASSED
tests/test_app.py::test_api_requires_key[get-/api/commands-None] PASSED
tests/test_app.py::test_api_requires_key[patch-/api/commands/1-body2] PASSED
tests/test_app.py::test_api_requires_key[post-/api/outputs-body3] PASSED
tests/test_app.py::test_api_requires_key[put-/api/monitor-body4] PASSED
tests/test_app.py::test_api_rejects_wrong_key[post-/api/events-body0] PASSED
tests/test_app.py::test_api_rejects_wrong_key[get-/api/commands-None] PASSED
tests/test_app.py::test_api_rejects_wrong_key[patch-/api/commands/1-body2] PASSED
tests/test_app.py::test_api_rejects_wrong_key[post-/api/outputs-body3] PASSED
tests/test_app.py::test_api_rejects_wrong_key[put-/api/monitor-body4] PASSED
tests/test_app.py::test_api_rejects_empty_key[post-/api/events-body0] PASSED
tests/test_app.py::test_api_rejects_empty_key[get-/api/commands-None] PASSED
tests/test_app.py::test_api_rejects_empty_key[patch-/api/commands/1-body2] PASSED
tests/test_app.py::test_api_rejects_empty_key[post-/api/outputs-body3] PASSED
tests/test_app.py::test_api_rejects_empty_key[put-/api/monitor-body4] PASSED
tests/test_app.py::test_api_rejects_every_key_when_there_are_no_agents[post-/api/events-body0] PASSED
tests/test_app.py::test_api_rejects_every_key_when_there_are_no_agents[get-/api/commands-None] PASSED
tests/test_app.py::test_api_rejects_every_key_when_there_are_no_agents[patch-/api/commands/1-body2] PASSED
tests/test_app.py::test_api_rejects_every_key_when_there_are_no_agents[post-/api/outputs-body3] PASSED
tests/test_app.py::test_api_rejects_every_key_when_there_are_no_agents[put-/api/monitor-body4] PASSED
tests/test_app.py::test_key_is_stored_as_fingerprint_and_encrypted_copy PASSED
tests/test_app.py::test_add_agent_with_own_key PASSED
tests/test_app.py::test_add_agent_generates_key_when_left_blank PASSED
tests/test_app.py::test_add_agent_rejects_bad_input[data0-Name can't be empty] PASSED
tests/test_app.py::test_add_agent_rejects_bad_input[data1-at most 50] PASSED
tests/test_app.py::test_add_agent_rejects_bad_input[data2-at least 20 characters] PASSED
tests/test_app.py::test_add_agent_rejects_bad_input[data3-no spaces] PASSED
tests/test_app.py::test_add_agent_rejects_duplicate_name_and_key PASSED
tests/test_app.py::test_add_agent_inside_folder_tags_it PASSED
tests/test_app.py::test_round_trip_between_agent_and_dashboard PASSED
tests/test_app.py::test_commands_only_go_to_their_own_agent PASSED
tests/test_app.py::test_agent_cannot_update_another_agents_command PASSED
tests/test_app.py::test_events_only_show_on_their_own_agent PASSED
tests/test_app.py::test_pending_commands_are_oldest_first PASSED
tests/test_app.py::test_empty_message_is_not_saved PASSED
tests/test_app.py::test_events_empty_state PASSED
tests/test_app.py::test_patch_missing_command_returns_404 PASSED
tests/test_app.py::test_rename_keeps_the_agent_connected PASSED
tests/test_app.py::test_rename_rejects_taken_or_empty_names PASSED
tests/test_app.py::test_create_folder_shows_in_sidebar PASSED
tests/test_app.py::test_duplicate_folder_name_shows_error PASSED
tests/test_app.py::test_folder_grid_shows_only_tagged_agents PASSED
tests/test_app.py::test_add_and_remove_tag PASSED
tests/test_app.py::test_adding_same_tag_twice_is_harmless PASSED
tests/test_app.py::test_rename_folder PASSED
tests/test_app.py::test_delete_folder_keeps_its_agents PASSED
tests/test_app.py::test_delete_agent_needs_the_edit_password PASSED
tests/test_app.py::test_delete_agent_denied_when_edit_password_env_is_empty PASSED
tests/test_app.py::test_delete_agent_removes_everything_it_owns PASSED
tests/test_app.py::test_agent_settings_hold_name_tags_key_and_delete PASSED
tests/test_app.py::test_agent_settings_start_closed PASSED
tests/test_app.py::test_settings_stay_open_after_rename_or_tag_change PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents-data0] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/command-data1] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/rename-data2] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/tags-data3] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/tags/1/remove-data4] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/delete-data5] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/key/view-data6] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/key/replace-data7] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/outputs/pin-data8] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/outputs/notify-data9] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/monitor-data10] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/agents/{id}/monitor/pin-data11] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/folders-data12] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/folders/1/rename-data13] PASSED
tests/test_app.py::test_dashboard_actions_need_csrf_token[/dashboard/folders/1/delete-data14] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents-data0] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/command-data1] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/rename-data2] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/tags-data3] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/tags/1/remove-data4] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/delete-data5] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/key/view-data6] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/key/replace-data7] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/outputs/pin-data8] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/outputs/notify-data9] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/monitor-data10] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/agents/{id}/monitor/pin-data11] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/folders-data12] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/folders/1/rename-data13] PASSED
tests/test_app.py::test_dashboard_actions_reject_wrong_csrf_token[/dashboard/folders/1/delete-data14] PASSED
tests/test_app.py::test_csrf_token_in_hidden_form_field_works PASSED
tests/test_app.py::test_csrf_token_only_on_pages_behind_login PASSED
tests/test_app.py::test_csrf_token_changes_with_the_password PASSED
tests/test_app.py::test_view_key_needs_the_edit_password PASSED
tests/test_app.py::test_view_key_shows_the_key PASSED
tests/test_app.py::test_view_key_for_agent_without_stored_copy PASSED
tests/test_app.py::test_view_key_when_encryption_secret_changed PASSED
tests/test_app.py::test_replace_key_needs_the_edit_password PASSED
tests/test_app.py::test_replace_key_generates_new_key_and_old_one_stops_working PASSED
tests/test_app.py::test_replace_key_with_own_key PASSED
tests/test_app.py::test_replace_key_rejects_bad_or_used_keys PASSED
tests/test_app.py::test_keys_need_the_encryption_secret PASSED
tests/test_app.py::test_sidebar_has_fold_button_info_and_connector PASSED
tests/test_app.py::test_connector_downloads_require_login PASSED
tests/test_app.py::test_connector_code_download PASSED
tests/test_app.py::test_connector_prompt_download PASSED
tests/test_app.py::test_connector_hint_uses_forwarded_https_address[https] PASSED
tests/test_app.py::test_connector_hint_uses_forwarded_https_address[https,http] PASSED
tests/test_app.py::test_new_agent_shows_both_connection_values PASSED
tests/test_app.py::test_unknown_connector_format_returns_404 PASSED
tests/test_app.py::test_output_kinds[Found 3 articles-text-Found 3 articles] PASSED
tests/test_app.py::test_output_kinds[42-number-42] PASSED
tests/test_app.py::test_output_kinds[3.5-number-3.5] PASSED
tests/test_app.py::test_output_kinds[https://example.com/story-link-https://example.com/story] PASSED
tests/test_app.py::test_output_kinds[content4-json-{\n  "top": "story"\n}] PASSED
tests/test_app.py::test_output_kinds[content5-json-[\n  1,\n  2\n]] PASSED
tests/test_app.py::test_output_kinds[True-text-true] PASSED
tests/test_app.py::test_output_kinds[javascript:alert(1)-text-javascript:alert(1)] PASSED
tests/test_app.py::test_output_kinds[see https://example.com-text-see https://example.com] PASSED
tests/test_app.py::test_output_category_must_be_1_to_50_characters[] PASSED
tests/test_app.py::test_output_category_must_be_1_to_50_characters[   ] PASSED
tests/test_app.py::test_output_category_must_be_1_to_50_characters[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx] PASSED
tests/test_app.py::test_output_content_cannot_be_empty_or_huge PASSED
tests/test_app.py::test_output_file_upload_and_download PASSED
tests/test_app.py::test_non_image_files_are_only_downloads[report.pdf-application/pdf] PASSED
tests/test_app.py::test_non_image_files_are_only_downloads[page.svg-image/svg+xml] PASSED
tests/test_app.py::test_non_image_files_are_only_downloads[page.html-text/html] PASSED
tests/test_app.py::test_output_file_size_limit PASSED
tests/test_app.py::test_output_file_name_is_cleaned PASSED
tests/test_app.py::test_output_file_download_needs_login_and_exists PASSED
tests/test_app.py::test_output_file_needs_api_key PASSED
tests/test_app.py::test_outputs_only_show_on_their_own_agent PASSED
tests/test_app.py::test_outputs_show_nothing_until_chosen PASSED
tests/test_app.py::test_pinned_category_starts_ticked PASSED
tests/test_app.py::test_outputs_filter_by_ticked_categories PASSED
tests/test_app.py::test_filter_button_summary PASSED
tests/test_app.py::test_outputs_sorting[date-desc-expected0] PASSED
tests/test_app.py::test_outputs_sorting[date-asc-expected1] PASSED
tests/test_app.py::test_outputs_sorting[category-asc-expected2] PASSED
tests/test_app.py::test_outputs_sorting[category-desc-expected3] PASSED
tests/test_app.py::test_outputs_sorting[content-asc-expected4] PASSED
tests/test_app.py::test_outputs_sorting[content-desc-expected5] PASSED
tests/test_app.py::test_unknown_sort_falls_back_to_newest_first PASSED
tests/test_app.py::test_filter_rows_only_resent_when_categories_change PASSED
tests/test_app.py::test_output_links_are_clickable_and_safe PASSED
tests/test_app.py::test_output_content_and_category_are_escaped PASSED
tests/test_app.py::test_pin_only_one_category_and_show_on_card PASSED
tests/test_app.py::test_pin_and_bell_keep_what_is_ticked PASSED
tests/test_app.py::test_agent_page_layout PASSED
tests/test_app.py::test_pinned_category_with_no_outputs_yet PASSED
tests/test_app.py::test_notify_toggle_is_saved PASSED
tests/test_app.py::test_deleting_agent_deletes_its_outputs_and_files PASSED
tests/test_app.py::test_agent_sets_and_clears_monitor PASSED
tests/test_app.py::test_monitor_must_be_http_or_https[javascript:alert(1)] PASSED
tests/test_app.py::test_monitor_must_be_http_or_https[ftp://example.com] PASSED
tests/test_app.py::test_monitor_must_be_http_or_https[example.com] PASSED
tests/test_app.py::test_user_sets_monitor_in_settings PASSED
tests/test_app.py::test_monitor_pdf_is_shown_inside_the_page PASSED
tests/test_app.py::test_monitor_pdf_must_be_a_real_pdf PASSED
tests/test_app.py::test_monitor_pdf_needs_key_and_login PASSED
tests/test_app.py::test_only_the_latest_monitor_is_kept PASSED
tests/test_app.py::test_monitor_section_only_refreshes_when_changed PASSED
tests/test_app.py::test_pin_monitor_shares_the_single_pin PASSED
tests/test_app.py::test_pinned_monitor_link_on_card PASSED
tests/test_app.py::test_activity_logs_output_and_monitor_updates PASSED
tests/test_app.py::test_long_output_is_shortened_in_activity PASSED
tests/test_app.py::test_deleting_agent_deletes_its_monitor_pdf PASSED
tests/test_app.py::test_pause_and_start_switch_the_paused_state PASSED
tests/test_app.py::test_check_in_keeps_agent_online PASSED
tests/test_app.py::test_messages_are_off_until_the_agent_accepts_them PASSED
tests/test_app.py::test_messages_ready_check PASSED
tests/test_app.py::test_agent_declares_its_check_in_interval PASSED
tests/test_app.py::test_check_in_interval_must_be_sensible[0] PASSED
tests/test_app.py::test_check_in_interval_must_be_sensible[-5] PASSED
tests/test_app.py::test_check_in_interval_must_be_sensible[604801] PASSED
tests/test_app.py::test_check_in_interval_must_be_sensible[often] PASSED
tests/test_app.py::test_online_follows_the_agents_own_rhythm[None-seen0-True] PASSED
tests/test_app.py::test_online_follows_the_agents_own_rhythm[None-seen1-False] PASSED
tests/test_app.py::test_online_follows_the_agents_own_rhythm[5-seen2-True] PASSED
tests/test_app.py::test_online_follows_the_agents_own_rhythm[5-seen3-False] PASSED
tests/test_app.py::test_online_follows_the_agents_own_rhythm[3600-seen4-True] PASSED
tests/test_app.py::test_online_follows_the_agents_own_rhythm[3600-seen5-False] PASSED
tests/test_app.py::test_online_follows_the_agents_own_rhythm[86400-seen6-True] PASSED
tests/test_app.py::test_online_follows_the_agents_own_rhythm[86400-seen7-False] PASSED
tests/test_app.py::test_check_in_interval_wording PASSED
tests/test_app.py::test_missing_columns_are_added_to_an_existing_database PASSED
tests/test_app.py::test_connector_check_in_declares_interval_and_handles_commands PASSED
tests/test_app.py::test_connector_check_in_without_handlers_only_checks_in PASSED
tests/test_app.py::test_connector_start_check_ins_runs_in_background PASSED
tests/test_app.py::test_connector_out_of_range_interval_is_clamped_not_an_error PASSED
tests/test_app.py::test_output_keeps_its_original_time PASSED
tests/test_app.py::test_future_times_become_now PASSED
tests/test_app.py::test_late_file_output_and_report PASSED
tests/test_app.py::test_late_monitor_never_replaces_a_newer_one PASSED
tests/test_app.py::test_connector_reports_to_any_address PASSED
tests/test_app.py::test_connector_handles_commands_and_marks_them_done PASSED
tests/test_app.py::test_connector_with_placeholders_does_nothing PASSED
tests/test_app.py::test_connector_explains_bad_settings[your-site.onrender.com-kkkkkkkkkkkkkkkkkkkk-must start with http] PASSED
tests/test_app.py::test_connector_explains_bad_settings[https://your-site.onrender.com--Set DASHBOARD_API_KEY] PASSED
tests/test_app.py::test_connector_explains_bad_settings[https://your-site.onrender.com-REPLACE_WITH_YOUR_AGENT_API_KEY-Set DASHBOARD_API_KEY] PASSED
tests/test_app.py::test_connector_warns_about_plain_http_on_remote_hosts PASSED
tests/test_app.py::test_connector_does_not_follow_redirects PASSED
tests/test_app.py::test_connector_explains_wrong_key PASSED
tests/test_app.py::test_connector_output_sends_content_and_category PASSED
tests/test_app.py::test_connector_output_sends_files PASSED
tests/test_app.py::test_connector_output_skips_oversize_and_missing_files PASSED
tests/test_app.py::test_connector_set_monitor PASSED
tests/test_app.py::test_connector_set_monitor_with_pdf PASSED
tests/test_app.py::test_buffer_saves_and_later_sends_with_original_time PASSED
tests/test_app.py::test_buffer_keeps_order PASSED
tests/test_app.py::test_buffer_survives_restart PASSED
tests/test_app.py::test_buffer_when_dashboard_unreachable PASSED
tests/test_app.py::test_buffer_copies_files PASSED
tests/test_app.py::test_buffer_keeps_only_latest_monitor PASSED
tests/test_app.py::test_mistakes_are_not_buffered PASSED
tests/test_app.py::test_buffer_has_a_size_limit PASSED
tests/test_app.py::test_connector_holds_outputs_while_paused PASSED
tests/test_app.py::test_connector_wait_if_paused PASSED
tests/test_app.py::test_connector_start_pause_commands_update_state PASSED
tests/test_app.py::test_connector_accept_messages PASSED
tests/test_app.py::test_messages_go_to_on_command_without_accept_messages PASSED
tests/test_app.py::test_connector_survives_unreachable_dashboard PASSED
tests/test_app.py::test_empty_grid_shows_only_add_agent_card PASSED
tests/test_app.py::test_grid_pages_hold_nine_cells_including_add_card PASSED
tests/test_app.py::test_no_page_buttons_when_everything_fits PASSED
tests/test_app.py::test_folder_page_buttons_keep_the_folder PASSED
tests/test_app.py::test_out_of_range_page_shows_last_page PASSED
tests/test_app.py::test_grid_cell_has_only_start_and_pause PASSED
tests/test_app.py::test_online_offline_and_never_connected_badges PASSED
tests/test_app.py::test_event_message_html_is_escaped PASSED
tests/test_app.py::test_agent_and_folder_names_are_escaped PASSED
tests/test_app.py::test_command_alert_html_is_escaped PASSED
tests/test_app.py::test_database_url_conversion[postgres://u:p@host:5432/db-postgresql+psycopg://u:p@host:5432/db] PASSED
tests/test_app.py::test_database_url_conversion[postgresql://u:p@host:5432/db-postgresql+psycopg://u:p@host:5432/db] PASSED
tests/test_app.py::test_database_url_conversion[postgresql+psycopg://u:p@host/db-postgresql+psycopg://u:p@host/db] PASSED
tests/test_app.py::test_database_url_conversion[sqlite:///./local.db-sqlite:///./local.db] PASSED
======================= 258 passed, 1 warning in 19.92s ========================
```

The one warning comes from Starlette and says its test client will move from `httpx` to a package called `httpx2`. It doesn't affect any results. Silencing it would mean installing a package that isn't on the allowed-dependency list, so it was left alone.

## 3. Manual end-to-end check (Instructions step 7)

This check was run on the first, single-agent version, which had the routes `/dashboard/events` and `/dashboard/command` and one shared `AGENT_API_KEY`. Those have since been replaced (see 3b and 3c).

**Result: PASSED.**

- **Setup:**
  - Started the server with `fastapi dev main.py --port 8765`.
  - Used temporary values for `AGENT_API_KEY`, `DASHBOARD_USER` and `DASHBOARD_PASSWORD`.
  - Pointed `DATABASE_URL` at a throwaway SQLite file outside the project, so `local.db` wasn't created.
  - Ran `agent/agent.py` with `SITE_URL=http://127.0.0.1:8765`.
- **Agent online:** `GET /dashboard/events` contained "Agent online".
- **Sending a command:** `POST /dashboard/command` (`command=message`, `text=hello from e2e`) returned the success alert, and `GET /api/commands` showed it as `pending`.
- **Agent picks it up:** within about 5 seconds the agent printed `Handling command 1: message`, sent the event "You said: hello from e2e" (visible in `/dashboard/events`), and marked the command done. `GET /api/commands` returned `[]`, and the database row's status was `done`.
- **Auth:** `/dashboard` with no login and `/api/commands` with no key both returned 401.
- **Server down:** run against a port where nothing was listening, the agent printed `Could not fetch commands (ConnectionError). Retrying in 3s.` and kept looping without crashing.
- **Missing key:** with `AGENT_API_KEY` empty, the agent exits with a clear message.
- **Browser check:** the pages were also checked in a browser at phone width:
  - The CDN styles load and the dark theme and Inter font apply.
  - The success alert disappears after about 3 seconds.
  - The text input clears after sending.
  - The activity list refreshes on its own, and HTML in a message shows as plain text.
- Both processes were stopped afterwards.

## 3b. Multi-agent dashboard check (after adding the grid)

This was run when agents still identified themselves by `AGENT_NAME`.

**Result: PASSED.**

- **Setup:**
  - Started the server on port 8000 with the temporary login `test` / `password` and a throwaway SQLite file outside the project.
  - Ran 11 copies of `agent/agent.py`, each with a different `AGENT_NAME` (alpha to kilo).
- **Grid:** page 1 showed alpha to india in a 3 × 3 grid, all marked "online", with « 1 2 » page buttons below. Page 2 showed juliet and kilo.
- **Grid buttons:** clicking **Pause** on alpha's card sent the command without leaving the page. Within 3 seconds the card's latest message changed to "Pausing." (the agent's reply). Clicking **Start** on bravo showed the pop-up "Sent "start" to bravo." in the corner.
- **Opening an agent:** clicking the body of alpha's card opened `/dashboard/agents/3`, alpha's control panel and activity log, showing "Pausing." and "Agent online".
- **Auth:** a wrong password returned 401.
- **Testing quirk:** if you log in by putting the credentials in the address bar (`http://test:password@...`), browsers refuse the page's background requests, so polling and buttons stop working. Logging in through the normal popup works correctly.

## 3c. Folders, Add Agent, rename, tags and delete

**Result: PASSED.**

- **Setup:**
  - Restarted the server on port 8000 with a fresh throwaway database, the login `test` / `password`, and the demo `DELETE_PASSCODE` `1234`.
  - Through the dashboard's own forms, created the folders Research and Writing and added 11 agents, each with its own key.
  - Tagged some agents with the folders, then ran 11 copies of `agent/agent.py`, each with a different key.
- **Grid:** All Agents showed the folder sidebar with correct counts, a 3 × 3 grid with folder tags on each card, and page buttons.
- **Folder view:** the Research folder showed only its agents, with the Add Agent card after them and Rename folder / Delete folder buttons.
- **Add Agent:** the card opened the Add Agent window, which said the agent would go into the open folder.
- **Agent page:** showed the name with an online badge, Rename, the folder tags with ×, a folder picker with + Add tag, and Delete agent.
- **Tag removal:** someone using the browser at the same time (not me) removed two tags from alpha, and the counts and grid updated correctly.
- **Delete** (on a throwaway agent):
  - A wrong passcode said "Wrong passcode. Nothing was deleted." and the agent stayed.
  - The right passcode deleted it and sent the browser back to `/dashboard`.
  - Its page then returned 404, and its key got 401.
- **Sorting fix found during the check:** an agent named "Bot" sorted ahead of "alpha" because the sort was case-sensitive. It now sorts A–Z ignoring case.

## 3d. CSRF protection, View key and Replace key

**Result: PASSED.**

- **Setup:**
  - Restarted the demo server with the agent editing password `1234` (renamed from the delete passcode) and a demo `KEY_ENCRYPTION_SECRET`.
  - Added the new `api_key_encrypted` column to the existing demo database instead of wiping it, so the user's own "Bot" agent and tag changes were kept.
  - Filled in encrypted copies for the 11 demo agents, whose keys were known. Bot's key was not known, so it shows the "use Replace key" message.
- **CSRF (over HTTP):**
  - The token appears on `/dashboard` but not on `/`.
  - Creating a folder with no token, or an agent with a wrong token, returned 403.
- **Keys, on a throwaway agent:**
  - View key with a wrong password showed only an error.
  - With the right password it showed the key, and that key worked for the API.
  - After Replace key, the old key got 401 and the new key got 200.
  - The throwaway agent was then deleted with the editing password.
- **In the browser:**
  - On alpha's page, View key opened its window. Entering the password and clicking Show key displayed `demo-key-alpha-0123456789`; this request carried the CSRF header from the page, or it would have been refused.
  - Pressing Escape closed the window and wiped the key from the page.

## 3e. Foldable sidebar, info window and Implement connector

**Result: PASSED.**

- **Connector, end to end:**
  - Downloaded `dashboard_connector.py` from the running dashboard. It came as a file attachment, with `http://127.0.0.1:8000` filled in. (This was the first version; section 3f covers the placeholder version.)
  - Added a throwaway agent, then ran a small "news agent" script that imported the connector and called `listen()` and `report()`.
  - Its "News agent online" and "Found: Example headline" reports appeared in the agent's activity log.
  - A message sent from the dashboard ("find more") reached the script's handler, which replied "News agent got: find more". The command was marked done, so none were left waiting.
  - Run with a wrong key, `report()` printed `Could not send report: HTTP 401 (is DASHBOARD_API_KEY right?)` and returned `False` without crashing.
  - The throwaway agent was then deleted.
- **Sidebar (at a 1280-pixel width):**
  - **«** moved the sidebar off-screen, and the grid used the full width.
  - **☰ Folders** appeared and brought the sidebar back.
  - The folded state was remembered after reloading the page.
- **Pop-ups:**
  - The ⓘ window showed the explanation.
  - In the Implement connector window, choosing **Code** showed the steps, a preview with the site's address, and **Download code**.
- **Testing quirk:** the built-in browser's screenshots often lagged behind the page, so most of these checks read the page's state through JavaScript rather than relying on screenshots.

## 3f. Connector that works wherever the dashboard runs

**Result: PASSED.**

- **Fresh download:** the address and key are marked `REPLACE THIS PLACEHOLDER` values, with only a "downloaded from: http://127.0.0.1:8000" hint filled in.
- **Placeholders untouched:** importing it printed "Not connected: Set DASHBOARD_URL …" and `report()` returned `False` without crashing.
- **Address copied with `/dashboard/` on the end:** it was tidied to `http://127.0.0.1:8000`, and the report reached a throwaway agent's activity log.
- **Rewritten demo agent** (`agent/agent.py`, now built on the connector):
  - It connected with `DASHBOARD_API_KEY`, went online, and replied "You said: portable hello" to a dashboard message.
  - With no key, it exited with a clear setup message.
- **Connector window:** shows "This dashboard's address".
- **Not checked on a real host:** a real Render or other HTTPS deployment wasn't available. Its behaviours (redirects, `https` hints, unreachable hosts) are covered by the stand-in website tests above.

## 3g. Agent settings pop-up

**Result: PASSED** (after one fix).

- **Your agent left alone:** on alpha's page, only the name, the gear icon, the status badge and the added/last-seen line showed. Clicking the gear opened **Agent settings** with Name, Folders, API key and the Danger zone. Nothing was changed on alpha.
- **Throwaway agent:**
  - Adding the Writing tag from settings showed it both on the page and in settings.
- **Bug found and fixed:** after that change, the pop-up closed by itself.
  - Cause: when HTMX swaps in a section, it briefly restores the `class` it received for elements that keep their `id`. That undid the `modal-open` Alpine had just added.
  - Fix: the server now writes `modal-open` into the HTML whenever settings should stay open, and a test checks for it.
- **After the fix:**
  - Removing and re-adding the tag kept settings open, and the tags on the page updated each time.
  - Delete with a wrong password said "Wrong agent editing password. Nothing was deleted."
  - The right password deleted the agent and returned to the dashboard; its page then returned 404.

## 3h. Outputs, pin, bell and Monitor

**Result: PASSED**, except embedding, which couldn't be confirmed here.

- **Setup:**
  - Restarted the demo server; the app had stopped it overnight.
  - Added an `outputs-demo` agent.
  - Through the real connector, sent text and a summary dict ("daily summary"), a number ("articles found"), a link ("links"), a generated PNG bar chart ("charts") and a PDF ("reports").
  - Set a monitor link with `set_monitor()`, and ran the demo agent with that agent's key; it added its own "links" output.
- **Outputs section:**
  - Showed 7 outputs and a filter button per category, each with a bell and pin.
  - The chart appeared as an image and the PDF as a download link.
  - The dict was shown as formatted JSON, and the links were clickable.
- **Filtering:** clicking "charts" showed only the chart, and the filter was still applied after the 3-second refresh.
- **Pin:** pinning "daily summary" put its latest output on the agent's grid card.
- **Monitor:**
  - Showed the label and link.
  - **Show here** created the embedded frame pointing at the link, but it stayed blank in the built-in browser. That may be because the built-in browser blocks outside sites, so embedding couldn't be confirmed here.
  - **Open ↗** and the explanation underneath cover sites that refuse embedding.

## 3i. PDF monitor, monitor pin and activity lines

**Result: PASSED.**

- **Setup:** generated two real 2-page PDFs ("Daily news summary - Oct 3" and "- Oct 4") with the standard library, and sent the first to outputs-demo with the connector's `set_monitor(Path(...), "Daily news summary")`.
- **Inline viewing:** the Monitor showed the PDF inside the page with the browser's own PDF viewer, including page thumbnails, "1 / 2", zoom, download and print, plus the label, file name and update time.
- **Scheduled update:**
  - With nothing new, the viewer stayed in place for over 10 seconds; the change check got "nothing new" each time.
  - After `set_monitor` with the Oct 4 PDF, the page swapped in the new PDF automatically within 10 seconds.
- **Pin:** clicking the Monitor's 📌 pinned it, and within one refresh the "daily summary" category's pin turned off. The grid card showed "📌 Monitor · Daily news summary" with `summary_Oct 4.pdf`.
- **Activity:** the log showed "Monitor updated: PDF summary_Oct 3.pdf" and "… Oct 4.pdf", each with its timestamp.

## 3j. New agent page layout and the Outputs Filter

**Result: PASSED** (after one styling fix).

- **Wide window (1280 pixels), outputs-demo:**
  - The order was Monitor (with the PDF), Outputs, then Activity, with Controls in the right-hand column.
  - After scrolling down to Outputs, Controls stayed in view, 24 pixels from the top.
- **Filter:**
  - Outputs started empty: "7 outputs available. Use Filter to choose…"; the Monitor was pinned, not a category.
  - In the Filter panel, ticking "links" then "charts" showed only those three outputs, and the button said "2 categories".
  - After a 3-second refresh the panel was still open, with the same ticks.
  - Choosing Category name and Ascending reordered the list (charts, then links).
- **Styling fix:** the chosen Ascending/Descending button wasn't highlighted. It now uses daisyUI's radio-button style, and the chosen button shows the primary colour.
- **Phone (375 × 812):** the right-hand column was hidden and Controls was a bar fixed to the bottom of the screen (Start, Pause, Message). The Monitor PDF showed above it.

## 3k. Offline buffer during a real outage

**Result: PASSED.**

- **The outage:** the dashboard server was actually down; the app had stopped it.
- **While it was down:** a small script using the connector (with outputs-demo's key and its own buffer folder) called `output("Made during the outage", "outage test")` and `report(...)`.
  - The output couldn't reach the dashboard and was saved: "Saved it to the offline buffer; will retry every 15s (1 waiting)".
  - The report queued behind it ("Queued send report behind 1 waiting item(s)"). Both calls returned `False`, and the script carried on.
  - The buffer file held 2 items.
- **Back up:** about 20 seconds later the dashboard was restarted. Within one retry (about 15 seconds) the script printed "Sent 2 saved item(s) from the offline buffer (0 still waiting)".
- **Result:** both items appeared in outputs-demo's Activity log, with the time they were made. They weren't marked "late", because they were under a minute old; the late label is covered by the automated tests.
- **Fix found along the way:** in the connector's warnings, the hints for 413 (file too big) and 422 (content rejected) could never show, because an earlier general branch caught them first. Fixed.

## 3l. Pause holds outputs, wait_if_paused, and opt-in messages

**Result: PASSED** (after fixing one real connector bug and making two tests deterministic).

- **Messages:** the demo agent (outputs-demo) called `accept_messages(...)`; the agent page showed the message box switched on and the badge "▶ running".
- **Pause:**
  - Pressing **Pause** changed the badge to "⏸ paused" straight away.
  - Within one check-in the agent printed "Paused from the dashboard: holding outputs…" and its work loop stopped ("waiting for Start...").
- **A message while paused:** its reply "You said: note while paused" (a `report()`) reached Activity, while its output ("Message received: …") was held: the agent printed "Held send output to 'messages' (1 waiting)", and the output wasn't on the dashboard.
- **Start:** the badge returned to "▶ running" and the agent printed "Started again from the dashboard". The held items were sent ("Sent 2 saved item(s)… 0 still waiting"); the held output appeared at its original time, 00:39:29, and the next tick followed.
- **Bug found and fixed:** while a retry was already running, an item dropped from a full buffer could still be sent. The retry now checks each item is still waiting just before sending it.
- **Test races fixed:** two tests occasionally failed because the connector's background retry sent an item just before the test cleared its record of requests. The data and order were correct. Tests now turn off background check-ins and retries and call `flush()` themselves. 10 consecutive full runs passed.

## 3m. Final check: connecting a separate project

**Result: PASSED.**

- **Reading the downloads as an outsider:**
  - The code download had two outdated spots: it pointed to "View key" on the agent's page, and its example handled messages the old way. Its opening instructions were rewritten as a complete quick start, with every function, the limits, and what Start/Pause and the offline buffer do.
  - The prompt download gained five things: file uploads are multipart forms, not JSON; the 20,000-character content and 50-character label limits and what 422 means; the "applied" field on monitor replies; message routing and that a command not marked done comes back again; and that a Python agent can use the ready-made code download.
- **A genuinely separate project:**
  - A new folder with its own Python environment containing only `requests`.
  - The connector was downloaded from the running dashboard, as a user would; the address and key came from environment variables.
  - The agent slot was added through the dashboard's Add Agent form, with a generated key.
  - The agent script used only what the quick start shows: `accept_messages`, `listen`, `report`, `set_monitor` (PDF), `output` (text, number, link, dict, PNG, PDF), `wait_if_paused`, and `flush`.
- **What happened:**
  - The agent switched messages on, and its Monitor showed the PDF (served as `application/pdf`). All six kinds of output arrived, in their categories.
  - A message ("focus on earnings") reached `on_message`.
  - After Pause, the work stopped (ticks stayed at 3 for 20 seconds). The message's output was held, while its status line still came through.
  - After Start, the held output arrived at its original time, the work resumed (ticks went on to 6), and the status lines read "Agent online, Paused, Started".
- **Project-wide checks:**
  - All 239 tests passed.
  - Every template is listed in the README.
  - `render.yaml` and `.env.example` list every secret.
  - Nothing secret or temporary would be committed (`.env`, `local.db` and buffer folders are ignored).

## 3n. Agent-defined check-ins

**Result: PASSED.**

- **Database upgrade step:** the local demo server restarted with the new code and printed "Database: added the new column agent.check_in_seconds". The new add-missing-columns step upgraded an existing database in place, as it will on the live Supabase database.
- **A scheduled "hourly" run:** a short script with alpha's key called `check_in(every=3600)`, sent an output, called `flush()` (0 waiting) and exited. The dashboard showed alpha as **online** with "checks in every 1 h", and the database recorded `check_in_seconds = 3600`.
- **Robustness fix:** the connector now ignores a commands reply that isn't a list (e.g. a proxy's error page) instead of failing.

## 3o. New look ("codepaper")

**Result: PASSED**, checked in the browser at a wide window and at phone size, after one fix.

- **Home:** yellow graph-paper page, the name "Ren" in IBM Plex Mono (letters stretched 10% wider) typing itself out, centred on the name alone (the blinking cursor sits just after it without affecting the centring), and a black "Open agent dashboard" button with yellow text.
- **Dashboard:** same layout. See-through deep-yellow cards (`#fff466` at 55%; the light blur was later removed for speed, see 3t) with black borders and hard shadows that lift on hover; the folders sidebar the same `#ffff83` as the page, see-through (45%); Start in vibrant yellow and Pause in white; the active folder in black; the pulsing light on "online".
- **Background grid:** squares turned 8° clockwise with a gentle 15° tilt, nearly flat, its near side towards a bearing of about 70° (east-north-east). It fades away on the opposite side and drifts along that bearing; the movement is set to stay on 70° despite the turn, and repeats seamlessly. Measured moving: it rushes in on page load, then drifts.
- **Second bug found and fixed:** with yellow cards, the grid disappeared. daisyUI paints the page's root element in the card colour, so the body's own yellow background covered the grid. The paper is now painted on the root and the body is transparent, so the grid sits between them.
- **Agent page:** same layout, with Controls still in the right-hand column. "// MONITOR", "// OUTPUTS", "// ACTIVITY" headings; the Monitor PDF works as before.
- **Pop-ups:** Agent settings, the Filter panel and toasts all appeared correctly.
- **Bug found and fixed:** the page-load animation left an invisible transform on each section, which trapped the settings window inside the header. The animation now leaves nothing behind (`animation-fill-mode: backwards`), and the window covers the screen again.
- **Tests:** all 258 automated tests still pass; only appearance changed.

## 3p. Agents read every agent's data, and delete only their own

**Result: PASSED** (automated tests; not yet checked on the live site).

- **New endpoints:** `GET /api/agents`, `GET /api/agents/{agent}` (with categories), `.../outputs`, `.../events`, `.../monitor`, `.../monitor.pdf`, and `GET /api/outputs/{id}/file` for reading; `DELETE /api/outputs/{id}`, `DELETE /api/outputs`, `DELETE /api/events/{id}`, `DELETE /api/events` and `DELETE /api/monitor` for deleting. `{agent}` is `me`, an id, or a name.
- **Reading:** an agent can read another agent's outputs (numbers and lists come back as sent; files are described and downloadable), activity (filterable by type), and monitor (link or PDF). Filters, paging and `since` work; a bad time or a `limit` over 500 gets 422.
- **Deleting:** an agent can delete its own outputs (their files go too), activity lines and monitor. Another agent's output or activity line gets 403 and nothing changes; bulk deletes only touch the caller's own data; a bulk delete with no filter gets 422 unless `all=true`.
- **Traceability:** every delete leaves an orange "delete" line in that agent's Activity log, shown on its page.
- **Privacy:** reads never include keys or the commands/messages sent to an agent. Every read and delete needs a valid key (401 otherwise).
- **Connector:** `agents`, `read_agent`, `read_outputs`, `read_activity`, `read_monitor`, `download`, `delete_output`, `delete_outputs`, `delete_event`, `delete_activity`. They never raise, refuse an unfiltered bulk delete before sending anything, and show the dashboard's reason for a refusal (e.g. "HTTP 403: Agents can only delete their own outputs").
- **Tests:** 17 new tests; all 275 pass.

## 3q. Agent descriptions

**Result: PASSED** (automated tests; not yet checked in the browser or on the live site).

- **Where it's written:** an optional "Description" box on the Add Agent card, and a "Description" section in Agent settings (saving it empty removes it). Up to 1,000 characters; line breaks are kept, ends trimmed, and runs of blank lines squeezed. Too long gets a clear error, keeping what was typed.
- **Where it's shown:** under the agent's name on its page, escaped so typed HTML shows as text.
- **Shared with agents:** `GET /api/agents` and `GET /api/agents/{agent}` (and the connector's `agents()` / `read_agent()`) include `description`.
- **Database upgrade:** an existing database built with the previous code gained the new column `agent.description` at startup ("Database: added the new column agent.description"), as the live Supabase database will on deploy.
- **Security:** changing it needs the dashboard login and the CSRF token. Agents can read descriptions but not change them.
- **Tests:** 5 new tests; all 280 pass.

## 3r. Long agent names on grid cards

**Result: PASSED**, checked in the browser at 800 px and 1440 px wide.

- **Bug:** a long name shared its line with the status badges, which never shrink, so "Quarterly Earnings Research Summariser Agent" with three folder tags showed as "Qua", with no "…" (daisyUI's title style blocks it).
- **Fix:** the name now wraps onto up to two lines (then "…"; hovering shows it all), and the badges move to the next line, on the right, when they don't fit. Short names look as before.

## 3s. Each device must sign in (login page replaces the pop-up)

**Result: PASSED** (automated tests and the browser; not yet checked on the live site).

- **Report:** after one device logged in, another could view the dashboard without logging in.
- **Investigation:** the live site refused every dashboard page without a login (401), and Cloudflare in front of Render reported `DYNAMIC` (not caching pages). So the server wasn't letting devices in. The cause was the browser login pop-up (HTTP Basic auth): it has no logout, browsers keep resending the password until they fully quit (phones rarely do), and synced password managers can bring it to other devices. Pages also didn't tell browsers not to store them.
- **Fix:**
  - A login page (`/login`) with one-day sign-ins per device, stored as fingerprints in a new `LoginSession` table. Log out, and "Sign out all devices", end sign-ins at once; changing the dashboard password ends them all. The pop-up is gone: even the right password sent the old way is refused.
  - The cookie is HttpOnly, SameSite=Lax, and Secure on the deployed site (not on `localhost`, where browsers would refuse it).
  - Every dashboard, API and login reply says `Cache-Control: no-store`.
- **In the browser:** opening an agent page signed out went to the login page and back after signing in. Deleting the sign-in while the page was open sent it to the login page within its 3-second refresh. Log out worked, and Back afterwards showed the login page.
- **Agents are unaffected:** the API still needs only the agent's key.
- **Tests:** 18 new tests (sign-in, wrong passwords, separate devices, logout, sign out all, expiry, password change, redirects for pages and HTMX, safe return addresses, cookie flags, no-store); all 299 pass.

## 3t. Lighter on the browser

**Result: PASSED** (automated tests and the browser; the effect on other tabs can't be measured from here).

- **Report:** the site made the browser, including other tabs, feel heavy.
- **Causes found:**
  - the background grid was moved by changing `background-position`, so the browser repainted a full-screen, 3D-tilted, faded layer about 60 times a second;
  - every card and the sidebar blurred what was behind them, recalculated every frame because the grid behind kept moving;
  - the grid, Activity and Outputs were rebuilt every 3 seconds even when nothing had changed, and kept polling in hidden tabs (with Tailwind's in-browser script rescanning each time).
- **Fixes:**
  - The grid is drawn once and only moved (an animated transform, done by the graphics card without repainting). It loops by 2 squares across and 1 down (about 1.5 degrees off the old 70-degree bearing) at the same speed; the page-load rush now covers 3 loops. The fade is now a fixed paper-coloured overlay painted once. Screenshots before and after match closely (fade strength tuned to match).
  - No blur behind cards, pop-ups and the sidebar (still just as see-through).
  - Self-refreshing sections send a fingerprint of what they show; the server answers "204 No Content" when nothing changed, and HTMX leaves the page alone. In the browser: the first grid check returned 15 KB, later ones 204 with about 300 bytes.
  - All self-refreshing (grid, Outputs, Activity, Monitor, messages check) pauses while the tab is hidden.
  - The stylesheet address now carries a fingerprint of the file (`theme.css?v=...`), so browsers fetch a changed stylesheet right after a deploy instead of using an old saved copy (found while testing).
- **No console errors** on the dashboard or agent page; the Outputs Filter still works.
- **Tests:** 4 new tests; all 303 pass.
- **Follow-up: Tailwind built ahead of time.** The in-browser Tailwind script (about 270 KB of JavaScript that worked out styles on every page) is replaced by `static/tailwind.css` (20 KB), built with Tailwind 4.3.3 from the templates and `main.py`. Every element's computed style (42 properties each) was recorded before and compared after, on the dashboard (266 elements), the agent page with and without the settings window and Filter open (475 each), and home: identical, apart from one button the mouse was hovering over at the time. A test checks the pages link the built file and that it contains classes the templates use.
- **Follow-up: stronger rush.** At the user's request, the page-load rush now covers 6 loops instead of 3 in the same 1.15 s. The sheet was enlarged so its edges stay out of view; checked at the rush's start, mid-rush, and through the drift, on 1920×1080 and 375×812 screens.
- **Tests:** 1 more test; all 304 pass.

## 3u. Icon control buttons, and a rush that carries on

**Result: PASSED** (automated tests and the browser).

- **Icons:** Start, Pause, Send, Message (phones) and a new Inbox button are icons (Heroicons, MIT), each with its name as a tooltip and for screen readers. The grid cards' Start/Pause match. On phones the order is Start, Pause, Inbox, Message, matching the wide-screen Controls (see 3v for the Inbox). Checked on the agent page at wide and phone sizes; the stylesheet was rebuilt for the new icon sizes.
- **Rush, reported problem:** each page restarted the grid from the same spot, so it seemed to snap back before rushing.
- **Fix:** `static/grid.js` saves the grid's position (per browser tab) when leaving a page, and the next page carries on from there (checked: the previous page left it at 0.975 of a loop; the next page picked up at 0.994, the difference being the load time). The rush is now a burst of speed in the drift itself: 30 loops (about 3,500 px, about 5 times further than before) over 1.6 s (later shortened at the user's request to 24 loops in 1.3 s, keeping the same starting speed), easing out, then the drift continues from wherever it ended. The sheet only ever moves within one loop, so it could be made smaller again.
- **Bug found and fixed while testing:** the rush was timed from page load, so in a tab not yet on screen it had "finished" before the first frame. It's now timed from the first frame drawn, so a page opened in a background tab rushes when first looked at.
- **Without JavaScript or with "reduce motion":** the grid drifts (or stays still) as before.
- **Tests:** all 304 pass.

## 3v. The Inbox

**Result: PASSED** (automated tests, and a real run with the demo agent).

- **What it is:** on an agent's page, the Inbox button opens a window to upload files for that agent (up to 50 MB each, with an optional note). They wait in the dashboard's database, visible only to that agent, until it takes them at a check-in and confirms; then they're deleted. Activity shows "Inbox: you uploaded…" and "Inbox: agent received…".
- **Storage:** files are stored and sent in 1 MB pieces (`InboxItem`, `InboxChunk`), so a large file never has to fit in the server's memory. Waiting files on all agents together are capped at 200 MB; a refused upload keeps nothing.
- **Agent side:** `accept_inbox(on_file)` in the connector downloads each waiting file to a temporary copy (streamed), calls `on_file(item, path)`, and confirms only if it returns normally. If it raises or returns `False`, the file stays for the next check-in. Also `inbox()`, `download_inbox()`, `confirm_inbox()`. The AI-assistant prompt describes the same.
- **Real run:** uploaded a 60-byte CSV and a 3 MB file (stored as 3 pieces) to a new "inbox-demo" agent before it was running; the agent page showed "2" on both Inbox buttons. Started the demo agent: it took both straight away, the received files were byte-for-byte identical, and the dashboard deleted both items and all their pieces.
- **Bugs found and fixed while testing:**
  - the wide-screen Inbox button did nothing (it wasn't inside an Alpine component);
  - pop-up windows had become hard to read (55% see-through, with the blur removed for speed): they're now solid, over a paper-coloured veil;
  - the warning in the Inbox window was split into odd columns.
- **Tests:** 12 new tests (upload in pieces, taking and deleting, privacy between agents, size limits, removing, login/CSRF/key, the page, agent deletion, and the connector's hand-over, keep-for-later and safe downloads); all 316 pass.

## 3w. Home page: centred name, guest sign-in and the tree

**Result: PASSED** (automated tests and the browser; the motion itself is best judged by eye).

- **Signed out:** "Ren" sits in the exact centre of the screen (measured: the name's centre and the screen's centre were both at 512, 384), with **Login** below and "as guest?" (slides out from under Login on hover; always shown on phones).
- **Signing in:** Login goes through the sign-in page and comes back to `/?entered`; "as guest?" signs in as `guest` and comes back the same way. There, the Login button glides to the root's place, the name fades, the root appears as **Ren** or **Guest**, the dashed lines draw out, and the leaves arrive one by one. The address then becomes plain `/`, so reloading shows the finished tree.
- **The tree:** a root card on the left and three leaves (**Dashboard**, open; **Portfolio** and **Data tracking**, marked "soon"), styled after a tech tree in the codepaper look. Phones get a vertical tree. The root card has a "log out" link.
- **Checked in the browser:** start and end states of the build, the finished tree on a wide screen and a phone, guest and owner roots. In the hidden test pane, animations only move while the pane is drawn, so the middle of the glide couldn't be captured; a page opened in a background tab likewise plays its build when first looked at.
- **Fixed while testing:** the Login button had shrunk to its text's width after the layout change.
- **Follow-up changes (user's requests):** the name's *base* is now on the screen's centre line (measured: 384 and 384); log out goes to the front page (from the tree and the dashboard); the root tech shows only "Ren"/"Guest" and "signed in", on one line, vertically centred; hovering it shows "Log out" and clicking it logs out (checked: it logged out and landed on the front page). As Ren, hovering the badge spins it into a cog, and clicking toggles developer mode ("developer mode" status, cog stays, remembered in the browser; checked on and off). Guests get no cog.
- **Phones (simulated touch events):** holding the badge shows the cog and letting go hides it, without switching modes; a quick tap switches developer mode; a plain tap on the card does not log out; holding it shows "Log out"; the next tap logs out. All as intended.
- **Tests:** 7 new or updated tests; all 322 pass.

## 3x. Developer mode settings, and log out vs. sign out

**Result: PASSED** (automated tests and the browser).

- **Sign-in card** no longer says "Agent Dashboard"; the dashboard has no Log out button.
- **Front page and tree:** the tree moved to `/tree`; `/` always shows the name and Login, and Login goes straight into the tree when already signed in.
- **Root tech:** hover shows "Log out / Hold to sign out" on one line (the root was widened after it wrapped). A click went to the front page and stayed signed in (checked). Holding the mouse down rewrote the word letter by letter, then signed out, measured: Log out → Lo out (332 ms) → L out → " out" → S out → Si out → Sig out → Sign out (1,052 ms), then the device was signed out and on the front page. Letting go early restores "Log out"; on phones the first hold reveals it and holding on signs out.
- **Developer mode** starts off on every visit to the tree. In it, a leaf tech opens its settings: a three-stop slider (Open / Private / Hidden), saved straight away and shown on the tech; Data tracking also has a page-wide API key to set, show or randomize (stored encrypted).
- **Server-side rules:** only the owner can use the settings (guests get 403); guests see Private techs greyed out and can't open them, don't see Hidden ones, and are kept out of a Private/Hidden dashboard even by typing its address (redirected to the tree; partial requests get 403).
- **Tests:** 10 new or rewritten tests; all 329 pass.

## 3y. Tech descriptions, and several accounts per device

**Result: PASSED** (automated tests and the browser).

- **Descriptions:** in developer mode, each tech's settings have a description box (up to 120 characters, with a live counter; extra spaces tidied; empty restores the original). In the browser, a longer Portfolio description saved straight away, the tech grew from 76 to 105 px tall, and the lines re-joined. Too long is refused; guests can't change it.
- **Several accounts:** a device can hold one sign-in per account. Checked: signed in as Ren, then "as guest?" showed Guest (the explicit choice); Login then went straight in as Ren (the highest account), without the password; "as guest?" again reused the same guest sign-in; holding sign-out ended both, and Login then asked for the password. A guest-only device goes in as Guest on Login.
- **Also:** the slider lost a stray box it had inherited from text fields.
- **Tests:** 3 new tests; all 332 pass.

## 3z. Rearranging techs by dragging (developer mode)

**Result: PASSED** (automated tests and the browser, with simulated pointer drags).

- In developer mode, dragging a leaf tech moves it; the others slide aside and the lines follow live. On release the order is saved (`POST /tree/techs/order`, owner only, every tech exactly once) and shown to guests too (hidden techs left out).
- **Checked in the browser:** dragging Data tracking from the bottom to the top: it had passed Portfolio halfway, settled at the top, and the server's order matched afterwards. The click a browser sends after a drag didn't open the settings; a plain click still did. The browser's own link dragging is blocked in developer mode so it can't cancel the drag.
- **Not done:** rearranging from the keyboard.
- **Tests:** 1 new test; all 333 pass.

## 3aa. Lighter pages: daisyUI built in, everything from this site, cached for good

**Result: PASSED** (automated tests and the browser).

- **Measured first:** the live site took 52 s to wake from sleep (Render's free plan) and about 0.25 s per request afterwards (Tokyo to Oregon). Instructions for both were given to the user (an uptime monitor; moving the service and database to Singapore); those are theirs to do.
- **daisyUI built in:** only the components the site uses are now built into `static/tailwind.css` (135 KB, about 20 KB to download), instead of the whole of daisyUI (1.1 MB) from the CDN. Every element's computed style on the front page, dashboard (with Add Agent open) and agent page (with settings, Filter and Inbox open) was compared before and after: the same, except invisible inputs, a timing artefact, and the phone Controls bar, whose 95% yellow background (always in its template) now actually works; its now-pointless blur was removed. The tree was checked by eye (its contents had changed in between).
- **Everything from this site:** HTMX 2.0.11, Alpine.js 3.17.4 and the IBM Plex Mono font (4 weights, Latin and extended Latin, with its OFL licence) are served from `static/`. In the browser: no requests to other servers; the font, HTMX and Alpine all worked.
- **Cached for good:** fingerprinted (`?v=...`) and versioned files are sent with `Cache-Control: public, max-age=31536000, immutable`, also on "not modified" answers (a first version missed those). On moving between pages, every file then came from the browser's cache without a request. Fingerprints are now worked out once per file version, not on every page.
- **Tests:** 3 new tests; all 336 pass.

## 4. Known limitations and things not verified

- **Render:** deployment was not tested. Only the user can do that, following the README. `render.yaml` parses as valid YAML and its field names were checked against Render's Blueprint reference, but Render itself has not validated it.
- **Postgres:** not tested against a real database. The `psycopg` driver is installed and the URL conversion is unit-tested, but the tests and the end-to-end check used SQLite.
- **Browser coverage:** the browser check above ran in one engine (Chromium) only. Other browsers and real phones were not tested.
- **Timestamps:** SQLite stores them without time-zone information. They are written in UTC and labelled UTC on the dashboard.
- **Polling:** the grid, Activity and Outputs check every 3 seconds, so new events can take up to 3 seconds to appear (and up to 3 seconds after returning to a hidden tab).
- **Refreshing grid:** the grid is only redrawn when something on it changed, but a button that is mid-click exactly when that happens can miss the click. Clicking again works. Server-Sent Events (see the README's next steps) would avoid this.
- **No login attempt limit:** wrong passwords on the login page aren't slowed down or blocked yet. Use a long, unique `DASHBOARD_PASSWORD`.
- **CSRF token never changes:** the token stays the same until `DASHBOARD_PASSWORD` changes, so anyone who sees a dashboard page's source could reuse it until then. They would still need your login to do anything.
- **No guessing limit:** wrong agent editing passwords are not rate-limited. Use one that's hard to guess.
- **Encryption secret:** if `KEY_ENCRYPTION_SECRET` is lost or changed, stored keys can't be viewed any more (the agents keep working). Replace key fixes each agent.
- **Sub-folder hosting:** the dashboard must be served at the root of a domain or subdomain, not under a sub-folder, because its pages use links starting with `/`.
- **Inbox files that are never taken** stay until you remove them (they count towards the 200 MB cap). There's no automatic expiry yet.
- **Storage:** output files live in the database, up to 5 MB each. Agents can delete their own old outputs, but there's no automatic clean-up on the dashboard's side yet. On a small free database, many files will fill it up.
- **Shared reading:** any agent key can read every agent's data. A leaked key exposes all agents' outputs, activity and monitors (but never keys or your messages), until it's replaced.
- **Deletes aren't buffered:** a delete made while the dashboard is unreachable is not retried, and it doesn't affect outputs still waiting in the agent's offline buffer.
- **Notifications:** the bell only saves a setting; nothing is sent until the Discord bot exists.
- **Monitor refresh:** the Monitor checks for changes every 10 seconds, so a new PDF or link can take up to 10 seconds to appear.
- **PDFs on phones:** some mobile browsers (notably iPhone Safari) only show the first page of a PDF inside a page; **Open ↗** shows the whole document.
- **Only the latest monitor is kept:** older monitor PDFs are deleted when replaced. For a history, also send them with `output()`.
- **Reaction time depends on each agent's rhythm:** Start, Pause and messages reach an agent at its next check-in, so an hourly agent reacts within the hour (`wait_if_paused()` checks every few seconds while waiting, though).
- **Pausing the work is up to the agent:** Pause always holds outputs and monitor updates. Stopping the agent's *work* needs `wait_if_paused()` in its loop, since the dashboard can't safely stop a program it doesn't control.
- **"Accepts messages" lasts until changed:** if an agent stops, its message box stays on, and messages wait until it's back. The agent switches it off only by checking in with `accepts_messages: false`, e.g. after restarting without `accept_messages()`.
- **Offline buffer scope:** it protects against the *dashboard* being unreachable. It can't help if the agent's own computer is off, or with Start/Pause/messages, which need the dashboard to be up when sent.
- **Short scripts:** a script that exits right after sending should call `flush()`; anything still waiting is sent on its next run.
- **Connector languages:** the ready-made code is Python only. For other languages, use the Prompt format with an AI assistant.
- **Older agents:** agents added before keys were encrypted (like the user's demo "Bot") can't have their key viewed until it is replaced.
- **Browser testing in the pane:** while the built-in browser was resized, clicks landed in the wrong place and screenshots sometimes lagged, so some interactions were checked through JavaScript or HTTP requests instead of real clicks.
