const express = require('express');

const app = express();
app.use(express.json());

const competitions = new Map();
let competitionSeq = 1;

const ARRIVAL_DISTANCE = 2.0;
const TEAM_WIN_ARRIVED_COUNT = 3;
const PORT = 3000;

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function getCompetitionOr404(res, competitionId) {
  const competition = competitions.get(competitionId);
  if (!competition) {
    res.status(404).json({ error: '竞赛不存在' });
    return null;
  }
  return competition;
}

function sendSseEvent(res, eventName, payload) {
  res.write(`event: ${eventName}\n`);
  res.write(`data: ${JSON.stringify(payload)}\n\n`);
}

function buildFinishedPayload(competition) {
  return {
    message: '竞赛已结束',
    competitionId: competition.id,
    status: '已结束',
    winnerTeamId: competition.winnerTeamId,
    finishedAt: competition.finishedAt
  };
}

function notifyCompetitionFinished(competition) {
  const payload = buildFinishedPayload(competition);
  for (const clientSet of competition.subscribers.values()) {
    for (const client of clientSet) {
      sendSseEvent(client, 'competition-finished', payload);
    }
  }
}

app.get('/health', (req, res) => {
  res.json({ message: '服务运行正常' });
});

app.post('/competitions', (req, res) => {
  const x = toNumber(req.body.x);
  const y = toNumber(req.body.y);

  if (x === null || y === null) {
    return res.status(400).json({ error: '终点坐标 x、y 必须提供且为数值' });
  }

  const competitionId = `COMP_${competitionSeq++}`;
  competitions.set(competitionId, {
    id: competitionId,
    target: { x, y },
    finished: false,
    winnerTeamId: null,
    finishedAt: null,
    createdAt: new Date().toISOString(),
    teams: new Map(),
    subscribers: new Map()
  });

  res.status(201).json({
    message: '竞赛创建成功',
    competitionId,
    target: { x, y }
  });
});

app.post('/competitions/:competitionId/teams', (req, res) => {
  const { competitionId } = req.params;
  const competition = getCompetitionOr404(res, competitionId);
  if (!competition) {
    return;
  }

  if (competition.finished) {
    return res.status(400).json({ error: '竞赛已结束，不能再创建团队' });
  }

  const teamId = typeof req.body.teamId === 'string' ? req.body.teamId.trim() : '';
  if (!teamId) {
    return res.status(400).json({ error: 'teamId 不能为空' });
  }

  if (competition.teams.has(teamId)) {
    return res.status(400).json({ error: '该竞赛中团队ID已存在' });
  }

  competition.teams.set(teamId, {
    teamId,
    createdAt: new Date().toISOString(),
    members: new Map(),
    arrivedMembers: new Set()
  });

  res.status(201).json({
    message: '团队创建成功',
    competitionId,
    teamId
  });
});

app.post('/reports', (req, res) => {
  const competitionId = req.body.competitionId ?? req.body.compId;
  const { teamId, memberId } = req.body;
  const x = toNumber(req.body.x);
  const y = toNumber(req.body.y);

  if (!competitionId || !teamId || !memberId || x === null || y === null) {
    return res.status(400).json({
      error: '提交数据缺失，必须包含 competitionId、teamId、memberId、x、y'
    });
  }

  const competition = getCompetitionOr404(res, competitionId);
  if (!competition) {
    return;
  }

  const team = competition.teams.get(teamId);
  if (!team) {
    return res.status(404).json({ error: '团队不存在' });
  }

  if (competition.finished) {
    return res.json(buildFinishedPayload(competition));
  }

  const reportTime = new Date().toISOString();
  const distance = Math.hypot(x - competition.target.x, y - competition.target.y);

  let member = team.members.get(memberId);
  if (!member) {
    member = {
      memberId,
      arrived: false,
      arrivedAt: null,
      lastPosition: null,
      lastReportAt: null
    };
    team.members.set(memberId, member);
  }

  member.lastPosition = { x, y };
  member.lastReportAt = reportTime;

  let memberArrivedNow = false;
  if (distance < ARRIVAL_DISTANCE && !member.arrived) {
    member.arrived = true;
    member.arrivedAt = reportTime;
    team.arrivedMembers.add(memberId);
    memberArrivedNow = true;
  }

  if (team.arrivedMembers.size >= TEAM_WIN_ARRIVED_COUNT && !competition.finished) {
    competition.finished = true;
    competition.winnerTeamId = teamId;
    competition.finishedAt = reportTime;

    notifyCompetitionFinished(competition);

    return res.json({
      message: '该团队率先夺标，竞赛结束',
      competitionId,
      status: '已结束',
      winnerTeamId: teamId,
      finishedAt: reportTime,
      reportTime,
      memberArrived: true,
      memberArrivedNow,
      teamArrivedCount: team.arrivedMembers.size
    });
  }

  res.json({
    message: '位置上报成功',
    competitionId,
    status: '未结束',
    reportTime,
    distance: Number(distance.toFixed(3)),
    memberArrived: distance < ARRIVAL_DISTANCE,
    memberArrivedNow,
    teamArrivedCount: team.arrivedMembers.size
  });
});

app.get('/competitions/:competitionId/target', (req, res) => {
  const { competitionId } = req.params;
  const competition = getCompetitionOr404(res, competitionId);
  if (!competition) {
    return;
  }

  if (competition.finished) {
    return res.json(buildFinishedPayload(competition));
  }

  res.json({
    competitionId,
    status: '未结束',
    target: competition.target
  });
});

app.get('/competitions/:competitionId/status', (req, res) => {
  const { competitionId } = req.params;
  const competition = getCompetitionOr404(res, competitionId);
  if (!competition) {
    return;
  }

  if (competition.finished) {
    return res.json(buildFinishedPayload(competition));
  }

  res.json({
    competitionId,
    status: '未结束'
  });
});

app.get('/competitions/:competitionId/stream', (req, res) => {
  const { competitionId } = req.params;
  const teamId = typeof req.query.teamId === 'string' ? req.query.teamId.trim() : '';
  const memberId = typeof req.query.memberId === 'string' ? req.query.memberId.trim() : '';

  const competition = getCompetitionOr404(res, competitionId);
  if (!competition) {
    return;
  }

  if (!teamId || !memberId) {
    return res.status(400).json({ error: 'teamId 和 memberId 不能为空' });
  }

  if (!competition.teams.has(teamId)) {
    return res.status(404).json({ error: '团队不存在，无法建立通知通道' });
  }

  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  if (typeof res.flushHeaders === 'function') {
    res.flushHeaders();
  }

  const subscriberKey = `${teamId}:${memberId}`;
  if (!competition.subscribers.has(subscriberKey)) {
    competition.subscribers.set(subscriberKey, new Set());
  }

  const clientSet = competition.subscribers.get(subscriberKey);
  clientSet.add(res);

  sendSseEvent(res, 'connected', {
    message: '通知通道已建立',
    competitionId,
    teamId,
    memberId
  });

  if (competition.finished) {
    sendSseEvent(res, 'competition-finished', buildFinishedPayload(competition));
    return res.end();
  }

  const heartbeat = setInterval(() => {
    res.write(': keepalive\n\n');
  }, 15000);

  req.on('close', () => {
    clearInterval(heartbeat);
    clientSet.delete(res);
    if (clientSet.size === 0) {
      competition.subscribers.delete(subscriberKey);
    }
  });
});

app.listen(PORT, () => {
  console.log(`夺标位置服务已启动: http://127.0.0.1:${PORT}`);
});
