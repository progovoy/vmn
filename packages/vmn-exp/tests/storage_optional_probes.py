"""Every ``hasattr(x, "name")`` / ``getattr(x, "name", default)`` probe in the
vmn_exp src roots, by name and count (plan 41 D12; test_storage_optional_surface.py).

Hand-kept, and only shrinks: a count goes down (or a name goes) in the commit
that removes a probe. A new probe fails the test until it is classified here.

The scan cannot tell what the receiver is, so the 2026-11-11 seed was split by
reading each call site once:

- ``STORAGE_PROBES``: a storage object (or one of its sides, ``_local`` /
  ``_remote``, or what its ``direct_files()`` returns) is probed. This is the
  optional storage surface; experiments.md "Optional methods" lists exactly
  these names with what a store without them gets. Private reach-ins
  (``_local``, ``_remote``, ``_s3``, ``_journal_sink``, ``_format_warned``)
  count too. ``endpoint_url`` and ``root`` are listed for their one storage
  site (storage/store_marker.py); their other sites probe argparse namespaces.
- ``OTHER_PROBES``: everything else -- argparse namespaces, request/app state,
  the index and its SQLite store, ML framework objects, exceptions, modules
  (``os``, ``sys``, ``signal``), a store's own client (``_own_client``,
  ``server_side_start_after``) and thread-locals (``depth``, ``busy``).

Removing the probes (base-class defaults instead) is plan 41 D17, parked.
"""

STORAGE_PROBES = {
    '_format_warned': 1,
    '_journal_sink': 1,
    '_local': 4,
    '_remote': 3,
    '_s3': 1,
    'append_log_entries': 1,
    'area': 1,
    'cache_identity': 3,
    'compact_log_segments': 2,
    'compacting': 1,
    'create_exclusive': 1,
    'create_log_segment': 1,
    'defer_ships': 2,
    'direct_files': 5,
    'endpoint_url': 4,
    'has_pending': 1,
    'in_area': 2,
    'index_cache_path': 2,
    'io_process_args': 1,
    'is_remote': 7,
    'list_artifacts': 1,
    'list_files': 1,
    'list_files_between': 1,
    'list_record_keys': 2,
    'list_record_names': 5,
    'list_run_verstrs': 3,
    'list_verstrs': 2,
    'listing_position': 1,
    'load_file_with_token': 1,
    'load_logs_by_writer': 3,
    'load_merged_log': 1,
    'local_record_dir': 1,
    'log_object_groups': 1,
    'metric_objects': 7,
    'metric_objects_listed': 1,
    'mirror_record': 1,
    'open_artifact': 1,
    'plain_record_dir': 1,
    'presign_artifact': 1,
    'read_class': 1,
    'record_files': 3,
    'record_name_pages': 1,
    'record_names_sig': 2,
    'remote_for': 1,
    'root': 1,
    'save_file_if_match': 1,
    'stream_files': 2,
    'stream_owner': 1,
    'undefer_ships': 2,
    'worker_spec': 1,
}

OTHER_PROBES = {
    'BaseEstimator': 1, 'CSafeLoader': 1, 'JOINS_KV': 1, 'Model': 1, 'SIGUSR1': 1, 'SIGUSR2': 1,
    'Trainer': 3, '__module__': 1, '__qualname__': 1, '__spec__': 1, '_after_fork_in_child': 1,
    '_base': 1, '_ctx_prev': 1, '_derived_on': 1, '_export_env': 1, '_finished': 1,
    '_is_gil_enabled': 4, '_media_steps': 2, '_own_client': 1, '_storage': 2, '_up': 1,
    'action': 3, 'adopt': 1, 'adopt_run': 1, 'alias': 2, 'alias_version': 1, 'all_apps': 1,
    'all_estimators': 1, 'all_finished': 1, 'allowed_host': 1, 'app': 1, 'app_name': 8,
    'archived': 2, 'args': 1, 'artifact': 1, 'audit': 2, 'auth_enabled': 4, 'background': 1,
    'best_params_': 1, 'best_score_': 1, 'bucket': 3, 'built': 1, 'busy': 1,
    'callback_handler': 1, 'callback_metrics': 1, 'callbacks': 1, 'capture_env': 3,
    'capture_output': 1, 'close': 1, 'code': 3, 'columns': 1, 'command': 1, 'compact': 2,
    'config': 4, 'conn': 1, 'context': 1, 'context_file': 1, 'control_plane': 1,
    'create_module': 1, 'dataset_inputs': 1, 'db': 1, 'define_metric': 1, 'depth': 3,
    'deriving': 1, 'description': 1, 'detach': 1, 'digest': 2, 'dir': 1, 'directions': 3,
    'drift': 1, 'dry_run': 4, 'dtype': 1, 'end_time': 1, 'expect': 1, 'experiment': 2,
    'experiment_dir': 2, 'file': 2, 'find_spec': 1, 'force': 2, 'fork_from': 1, 'fork_step': 1,
    'from_journal': 1, 'from_snapshot': 4, 'frozen': 1, 'full_listing_due': 1, 'full_log': 2,
    'generation': 1, 'get_params': 1, 'getuid': 1, 'global_step': 1, 'heartbeat_interval': 1,
    'history': 1, 'hparams': 1, 'id': 1, 'include_deleted': 1, 'inputs': 4, 'intent': 1,
    'intent_file': 1, 'interval_sec': 1, 'is_world_process_zero': 1, 'item': 2, 'journal_at': 1,
    'journaled': 1, 'json': 6, 'keep': 2, 'keep_warm': 2, 'keras': 1, 'keys': 1,
    'kill_grace_sec': 1, 'kind': 3, 'kv_get_many': 1, 'kv_put_many': 1, 'last': 3,
    'last_error': 1, 'last_refresh_at': 1, 'latest': 3, 'lazy_records': 1, 'leading': 2,
    'learning_rate': 1, 'live': 1, 'load_kept': 1, 'load_lazy': 1, 'load_newest': 1,
    'load_warm': 1, 'loading': 1, 'local_only': 1, 'loss': 1, 'max_bytes': 2, 'max_epochs': 1,
    'metrics': 1, 'metrics_ended_hours': 2, 'metrics_format': 1, 'mlruns': 2, 'mode': 1,
    'model_name': 5, 'name': 2, 'new_app': 1, 'no_trim_journal': 1, 'num_fds': 1,
    'number_later': 1, 'of_verstrs': 1, 'older_than': 2, 'optimizer': 1, 'org_id': 1,
    'output': 1, 'output_cap_mb': 1, 'output_dir': 1, 'overflowed': 1, 'parent': 2, 'patch': 2,
    'path': 4, 'pid': 1, 'precision': 1, 'prefetch': 1, 'prefix': 4, 'principal': 4,
    'process_cpu_count': 1, 'protect_tag': 2, 'published': 1, 'published_at': 1, 'pytorch': 1,
    'query': 7, 'read': 1, 'record_count': 1, 'recording': 1, 'refresh_features': 1,
    'refreshing': 1, 'refs': 2, 'register_at_fork': 4, 'remove': 2, 'repo': 2, 'repo_lock': 4,
    'response': 2, 'resume_journal': 1, 'role_mappings': 4, 'router': 2, 'rows': 1,
    'run_cmd': 5, 'run_name': 3, 'run_state': 2, 'save': 1, 'savefig': 1,
    'sched_getaffinity': 1, 'schema_less': 1, 'scope': 2, 'score': 1, 'select': 1,
    'server_side_start_after': 2, 'shape': 2, 'similar_hint': 1, 'skip_artifacts': 1,
    'snapshot_now': 1, 'statfs$INODE64': 1, 'status_code': 5, 'step': 1, 'store': 6,
    'sync_interval': 1, 'system_metrics': 1, 'tenancy': 1, 'to_dict': 3, 'token': 2,
    'tolist': 1, 'tool': 1, 'top': 1, 'tracking_uri': 2, 'ui_args': 2, 'untracked_paths': 1,
    'up_moved': 1, 'uri': 2, 'use_io_process': 1, 'version': 10, 'version_ref': 2,
    'vmn_root_path': 2, 'wake_key': 1, 'workers': 1, 'world_size': 1, 'writer_id': 2, 'yes': 1,
}
