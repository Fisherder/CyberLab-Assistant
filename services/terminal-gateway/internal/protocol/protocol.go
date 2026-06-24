package protocol

const (
	ClientStdin     byte = 0x01
	ClientResize    byte = 0x02
	ClientAck       byte = 0x03
	ClientHeartbeat byte = 0x04

	ServerStdout byte = 0x11
	ServerStatus byte = 0x12
	ServerReplay byte = 0x13
	ServerError  byte = 0x1F
)

type ErrorCode string

const (
	ErrTicketExpired ErrorCode = "TERMINAL_TICKET_EXPIRED"
	ErrReplayGap     ErrorCode = "TERMINAL_REPLAY_GAP"
	ErrBadFrame      ErrorCode = "BAD_TERMINAL_FRAME"
)

