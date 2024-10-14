local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local HTTPService = game:GetService("HttpService")
local LocalizationService = game:GetService("LocalizationService")
local Countries = require(script:WaitForChild("Countries"))

local url = "etc/log"

local serverCreatedAt = os.time()
local playerJoinedAt = {}

local MAX_RETRIES = 3
local RETRY_DELAY = 1

local function getServerType()
	if RunService:IsStudio() then
		return 'StudioServer'
	else
		if game.PrivateServerId ~= "" then
			if game.PrivateServerOwnerId ~= 0 then
				return "VIPServer"
			else
				return "ReservedServer"
			end
		else
			return "StandardServer"
		end
	end
end

local function request(player, extra)
	local payload = {
		username = player.Name,
		userId = player.UserId,
		userAge = player.AccountAge,
		serverId = game.JobId,
		serverType = getServerType(),
		serverAge = os.time() - serverCreatedAt,
		playerCount = #game.Players:GetPlayers(),
		now = DateTime.now().UnixTimestampMillis
	}
	for k, v in pairs(extra) do
		payload[k] = v
	end
	local success, response
	for attempt = 1, MAX_RETRIES do
		success, response = pcall(function() 
			return HTTPService:PostAsync(url, HTTPService:JSONEncode(payload)) 
		end)
		if success then
			break
		end
		if attempt < MAX_RETRIES then
			task.wait(RETRY_DELAY)
		end
	end
end

Players.PlayerAdded:Connect(function(player)
	playerJoinedAt[player.UserId] = os.time()
	local success, country = pcall(function()
		return LocalizationService:GetCountryRegionForPlayerAsync(player)
	end)
	local extra = {
		userAge = player.AccountAge,
		userLocale = player.LocaleId,
		userCountry = Countries[country],
		userPing = player:GetNetworkPing(),
		userPremium = player.MembershipType == Enum.MembershipType.Premium
	}
	request(player, extra)
end)

Players.PlayerRemoving:Connect(function(player)
	local extra = {
		totalSeconds = os.time() - playerJoinedAt[player.UserId],
		usedFeature = shared[player]
	}
	request(player, extra)
	playerJoinedAt[player.UserId] = nil
end)

game:BindToClose(function() -- ensure last job finishes
	while next(playerJoinedAt) do
		task.wait(0.1)
	end
end)
