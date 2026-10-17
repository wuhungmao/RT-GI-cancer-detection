// CVAT UI plugin: adds "Track with MedSAM2" to the annotation page Menu.
// It sends the current job and frame to the MedSAM2 tracker service (tracker/server.py,
// routed at /medsam2-tracker/ on the CVAT address), shows its progress,
// and reloads the job's annotations when tracking finishes.
//
// Built into the CVAT UI by scripts/start_cvat.sh (copied to cvat/cvat-ui/plugins/medsam2-tracker).

import React, { useCallback, useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import Modal from 'antd/lib/modal';
import Button from 'antd/lib/button';
import InputNumber from 'antd/lib/input-number';
import Checkbox from 'antd/lib/checkbox';
import Progress from 'antd/lib/progress';
import Alert from 'antd/lib/alert';
import Space from 'antd/lib/space';
import Text from 'antd/lib/typography/Text';
import notification from 'antd/lib/notification';

import { type Job } from 'cvat-core-wrapper';
import { CombinedState } from 'reducers';
import { fetchAnnotationsAsync, saveAnnotationsAsync } from 'actions/annotation-actions';
import { ComponentBuilder, PluginEntryPoint } from 'components/plugins-entrypoint';

const API_URL = '/medsam2-tracker/api';
const OPEN_EVENT = 'medsam2-tracker.open';
const POLL_INTERVAL_MS = 1000;

interface RunStatus {
    state: 'queued' | 'running' | 'done' | 'failed';
    percent: number;
    message: string;
}

// An active run from GET /runs; other users' runs only have state, stage and percent
interface QueueEntry {
    mine: boolean;
    id?: string;
    job_id?: number;
    state: 'queued' | 'running';
    stage: string;
    percent: number;
    message?: string;
}

function getCookie(name: string): string {
    const cookie = document.cookie.split('; ').find((item) => item.startsWith(`${name}=`));
    return cookie ? decodeURIComponent(cookie.slice(name.length + 1)) : '';
}

async function callTracker(path: string, init: RequestInit = {}): Promise<any> {
    const response = await fetch(`${API_URL}${path}`, {
        ...init,
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
            ...(init.headers || {}),
        },
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
        throw new Error(body?.message || `The MedSAM2 tracker service is not available (HTTP ${response.status})`);
    }
    return body;
}

// Other active runs on the GPU, oldest (= running) first
function QueueList(
    { queue, currentRunID, currentJobID }: { queue: QueueEntry[], currentRunID: string | null, currentJobID: number },
): JSX.Element | null {
    const others = queue.filter((run) => !run.mine || run.id !== currentRunID);
    if (!others.length) return null;

    return (
        <Space direction='vertical' style={{ width: '100%', marginTop: 8 }} size={0}>
            <Text strong>{currentRunID ? 'Other tracking runs' : 'Tracking runs in progress'}</Text>
            {others.map((run, index) => {
                let name = "Another user's run";
                if (run.mine) {
                    name = run.job_id === currentJobID ? 'Your run on this job' : `Your run on job #${run.job_id}`;
                }
                const stage = run.state === 'queued' ? 'waiting' : (run.message ?? run.stage);
                return (
                    // eslint-disable-next-line react/no-array-index-key
                    <div key={run.id ?? index}>
                        <Text type='secondary'>{`${name}: ${stage}`}</Text>
                        <Progress percent={Math.floor(run.percent)} size='small' status={run.state === 'running' ? 'active' : 'normal'} />
                    </div>
                );
            })}
        </Space>
    );
}

function TrackerModal(): JSX.Element | null {
    const dispatch = useDispatch();
    const job = useSelector((state: CombinedState) => state.annotation.job.instance) as Job | null;
    const frame = useSelector((state: CombinedState) => state.annotation.player.frame.number);

    const [open, setOpen] = useState(false);
    const [start, setStart] = useState(0);
    const [stop, setStop] = useState(0);
    const [replace, setReplace] = useState(true);
    const [keyFrame, setKeyFrame] = useState(0);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [runID, setRunID] = useState<string | null>(null);
    const [status, setStatus] = useState<RunStatus | null>(null);
    const [queue, setQueue] = useState<QueueEntry[]>([]);

    const running = !!runID && !!status && ['queued', 'running'].includes(status.state);

    useEffect(() => {
        const onOpen = async (): Promise<void> => {
            if (!running && job) {
                setKeyFrame(frame);
                setStart(job.startFrame);
                setStop(job.stopFrame);
                setError(null);
                setRunID(null);
                setStatus(null);
                setQueue([]);
                // Reconnect to a run this user started earlier on this job (e.g. before leaving the page)
                try {
                    const active: QueueEntry[] = await callTracker('/runs');
                    setQueue(active);
                    const previous = active.find((run) => run.mine && run.job_id === job.id);
                    if (previous?.id) {
                        setStatus({ state: previous.state, percent: previous.percent, message: previous.message ?? '' });
                        setRunID(previous.id);
                    }
                } catch (e: any) {
                    setError(e.message);
                }
            }
            setOpen(true);
        };
        window.addEventListener(OPEN_EVENT, onOpen);
        return () => window.removeEventListener(OPEN_EVENT, onOpen);
    }, [running, job, frame]);

    const reloadAnnotations = useCallback(async (): Promise<void> => {
        if (!job) return;
        // Keep edits made while tracking ran, then load the new masks from the server
        if (job.annotations.hasUnsavedChanges()) {
            await dispatch(saveAnnotationsAsync() as any);
        }
        await job.annotations.clear({ reload: true });
        dispatch(fetchAnnotationsAsync() as any);
    }, [job]);

    // Poll the run while it is in progress; keeps going if the window is closed
    useEffect(() => {
        if (!runID) return undefined;
        let stopped = false;
        const poll = async (): Promise<void> => {
            try {
                const [result, active]: [RunStatus, QueueEntry[]] = await Promise.all([
                    callTracker(`/runs/${runID}`), callTracker('/runs'),
                ]);
                if (stopped) return;
                setStatus(result);
                setQueue(active);
                if (result.state === 'done') {
                    await reloadAnnotations();
                    notification.success({ message: 'MedSAM2 tracking finished', description: result.message });
                    return;
                }
                if (result.state === 'failed') {
                    notification.error({ message: 'MedSAM2 tracking failed', description: result.message });
                    return;
                }
            } catch (e: any) {
                if (stopped) return;
                setStatus({ state: 'failed', percent: 0, message: e.message });
                return;
            }
            setTimeout(poll, POLL_INTERVAL_MS);
        };
        poll();
        return () => { stopped = true; };
    }, [runID]);

    const onStart = async (): Promise<void> => {
        if (!job) return;
        setSubmitting(true);
        setError(null);
        try {
            // The tracker reads the key-frame annotations from the server, so save first
            if (job.annotations.hasUnsavedChanges()) {
                await dispatch(saveAnnotationsAsync() as any);
                if (job.annotations.hasUnsavedChanges()) {
                    throw new Error('Could not save the annotations. Save them (Ctrl+S) and try again.');
                }
            }
            const { id } = await callTracker('/runs', {
                method: 'POST',
                body: JSON.stringify({
                    job_id: job.id, frame: keyFrame, start, stop, replace,
                }),
            });
            setStatus({ state: 'queued', percent: 0, message: 'Starting...' });
            setRunID(id);
        } catch (e: any) {
            setError(e.message);
        } finally {
            setSubmitting(false);
        }
    };

    if (!job) return null;

    const rangeValid = start <= keyFrame && keyFrame <= stop;
    let footer: JSX.Element[];
    if (!runID) {
        footer = [
            <Button key='cancel' onClick={() => setOpen(false)}>Cancel</Button>,
            <Button key='start' type='primary' loading={submitting} disabled={!rangeValid} onClick={onStart}>
                Start tracking
            </Button>,
        ];
    } else {
        footer = [<Button key='close' type={running ? 'default' : 'primary'} onClick={() => setOpen(false)}>Close</Button>];
    }

    return (
        <Modal
            title='Track with MedSAM2'
            open={open}
            onCancel={() => setOpen(false)}
            footer={footer}
            destroyOnClose={false}
        >
            {!runID ? (
                <Space direction='vertical' style={{ width: '100%' }}>
                    <Text>
                        {`Every mask, polygon and box on frame ${keyFrame} (the current frame) will be tracked `}
                        through the frames below. Masks from MedSAM2 are added to the other frames.
                    </Text>
                    <Space>
                        <Text>From frame</Text>
                        <InputNumber
                            min={job.startFrame}
                            max={keyFrame}
                            value={start}
                            onChange={(value) => setStart(Number(value ?? job.startFrame))}
                        />
                        <Text>to frame</Text>
                        <InputNumber
                            min={keyFrame}
                            max={job.stopFrame}
                            value={stop}
                            onChange={(value) => setStop(Number(value ?? job.stopFrame))}
                        />
                    </Space>
                    <Checkbox checked={replace} onChange={(e) => setReplace(e.target.checked)}>
                        Replace masks from earlier MedSAM2 tracking (your own edits are kept)
                    </Checkbox>
                    {error && <Alert type='error' message={error} style={{ whiteSpace: 'pre-wrap' }} />}
                    <QueueList queue={queue} currentRunID={null} currentJobID={job.id} />
                </Space>
            ) : (
                <Space direction='vertical' style={{ width: '100%' }}>
                    <Progress
                        percent={Math.floor(status?.percent ?? 0)}
                        status={status?.state === 'failed' ? 'exception' : (status?.state === 'done' ? 'success' : 'active')}
                    />
                    {status?.state === 'failed' ? (
                        <Alert type='error' message={status.message} style={{ whiteSpace: 'pre-wrap' }} />
                    ) : (
                        <Text>{status?.message}</Text>
                    )}
                    {running && (
                        <Text type='secondary'>
                            You can close this window and keep working. A message appears when tracking finishes,
                            and the new masks are loaded automatically.
                        </Text>
                    )}
                    {running && <QueueList queue={queue} currentRunID={runID} currentJobID={job.id} />}
                </Space>
            )}
        </Modal>
    );
}

// Annotation menu items are plain antd menu item objects, built by calling this function
function TrackMenuItem(): object {
    return {
        key: 'medsam2-track',
        label: 'Track with MedSAM2',
        onClick: () => window.dispatchEvent(new CustomEvent(OPEN_EVENT)),
    };
}

const builder: ComponentBuilder = ({ dispatch, actionCreators }) => {
    dispatch(actionCreators.addUIComponent('annotationPage.menuActions.items', TrackMenuItem as any, { weight: 45 }));
    // The player slider is always shown on the annotation page; it hosts the (hidden) modal
    dispatch(actionCreators.addUIComponent('annotationPage.player.slider', TrackerModal));

    return {
        name: 'MedSAM2 tracker',
        destructor: () => {
            dispatch(actionCreators.removeUIComponent('annotationPage.menuActions.items', TrackMenuItem as any));
            dispatch(actionCreators.removeUIComponent('annotationPage.player.slider', TrackerModal));
        },
    };
};

function register(): void {
    if (Object.prototype.hasOwnProperty.call(window, 'cvatUI')) {
        (window as any as { cvatUI: { registerComponent: PluginEntryPoint } })
            .cvatUI.registerComponent(builder);
    }
}

window.addEventListener('plugins.ready', register, { once: true });
