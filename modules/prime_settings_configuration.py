#!/usr/bin/env python3
"""
Prime Settings Configuration
===========================

Centralized configuration validation and management system for The Easy ORB Strategy.
Provides comprehensive configuration validation, environment setup, and runtime configuration
management with automatic error detection and correction.

Key Features:
- Comprehensive configuration validation on startup
- Environment variable management and validation
- Runtime configuration updates with validation
- Configuration backup and restore capabilities
- Automatic configuration optimization
- Error detection and correction suggestions
- Configuration documentation generation

Author: Easy ORB Strategy Development Team
Last Updated: January 6, 2026 (Rev 00231)
Version: 2.31.0
"""

import os
import json
import logging
import yaml
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import shutil
from collections import defaultdict

log = logging.getLogger("prime_settings_configuration")

# ============================================================================
# ENUMS
# ============================================================================

class ConfigSection(Enum):
    """Configuration section enumeration"""
    GENERAL = "general"
    TRADING = "trading"
    RISK = "risk"
    POSITION_SIZING = "position_sizing"
    DATA = "data"
    ALERTS = "alerts"
    ETrade = "etrade"
    TELEGRAM = "telegram"
    PERFORMANCE = "performance"
    STEALTH = "stealth"

class ConfigValidationLevel(Enum):
    """Configuration validation level"""
    BASIC = "basic"
    STANDARD = "standard"
    STRICT = "strict"
    PRODUCTION = "production"

class ConfigErrorType(Enum):
    """Configuration error type"""
    MISSING = "missing"
    INVALID = "invalid"
    OUT_OF_RANGE = "out_of_range"
    DEPRECATED = "deprecated"
    CONFLICT = "conflict"
    SECURITY = "security"

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class ConfigError:
    """Configuration error information"""
    section: ConfigSection
    key: str
    error_type: ConfigErrorType
    message: str
    current_value: Any = None
    expected_value: Any = None
    severity: str = "error"  # error, warning, info
    fix_suggestion: str = ""

@dataclass
class ConfigValidationResult:
    """Configuration validation result"""
    is_valid: bool
    errors: List[ConfigError] = field(default_factory=list)
    warnings: List[ConfigError] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    validation_time: datetime = field(default_factory=datetime.now)
    config_hash: str = ""

@dataclass
class ConfigBackup:
    """Configuration backup information"""
    timestamp: datetime
    config_data: Dict[str, Any]
    backup_path: str
    is_valid: bool
    error_count: int = 0

# ============================================================================
# CONFIGURATION VALIDATION RULES
# ============================================================================

class PrimeSettingsConfiguration:
    """
    Prime Settings Configuration Manager
    
    Centralized configuration validation and management system that ensures
    all system configurations are valid, optimized, and production-ready.
    """
    
    def __init__(self, config_path: str = "config/", validation_level: ConfigValidationLevel = ConfigValidationLevel.PRODUCTION):
        self.config_path = Path(config_path)
        self.validation_level = validation_level
        self.config_data = {}
        self.backup_dir = self.config_path / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Configuration validation rules
        self.validation_rules = self._initialize_validation_rules()
        
        # Load and validate configuration
        self.load_and_validate_config()
        
        log.info(f"🚀 Prime Settings Configuration initialized with {validation_level.value} validation")
    
    def _initialize_validation_rules(self) -> Dict[str, Dict[str, Any]]:
        """Initialize configuration validation rules"""
        return {
            ConfigSection.GENERAL.value: {
                "strategy_mode": {
                    "required": True,
                    "type": str,
                    "allowed_values": ["standard", "advanced", "quantum"],
                    "default": "standard"
                },
                "initial_capital": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1000,
                    "max_value": 1000000,
                    "default": 10000
                },
                "max_positions": {
                    "required": True,
                    "type": int,
                    "min_value": 1,
                    "max_value": 50,
                    "default": 15
                },
                "trading_enabled": {
                    "required": True,
                    "type": bool,
                    "default": True
                }
            },
            ConfigSection.TRADING.value: {
                "min_confidence": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.0,
                    "max_value": 1.0,
                    "default": 0.35
                },
                "min_quality_score": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.0,
                    "max_value": 100.0,
                    "default": 8.0
                },
                "max_daily_trades": {
                    "required": True,
                    "type": int,
                    "min_value": 1,
                    "max_value": 100,
                    "default": 20
                },
                "cooldown_minutes": {
                    "required": True,
                    "type": int,
                    "min_value": 1,
                    "max_value": 1440,
                    "default": 30
                },
                "base_position_size_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 20.0,
                    "default": 10.0,
                    "description": "Base position size percentage"
                },
                "max_position_size_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 10.0,
                    "max_value": 50.0,
                    "default": 35.0,
                    "description": "Maximum position size percentage"
                },
                "trading_cash_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 70.0,
                    "max_value": 90.0,
                    "default": 80.0,
                    "description": "Percentage of capital for trading"
                },
                "cash_reserve_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 10.0,
                    "max_value": 30.0,
                    "default": 20.0,
                    "description": "Percentage of capital reserved"
                }
            },
            ConfigSection.RISK.value: {
                "max_position_size": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.01,
                    "max_value": 1.0,
                    "default": 0.1
                },
                "max_daily_loss": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.01,
                    "max_value": 0.5,
                    "default": 0.05
                },
                "stop_loss_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.001,
                    "max_value": 0.1,
                    "default": 0.02
                },
                "take_profit_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.001,
                    "max_value": 0.5,
                    "default": 0.05
                }
            },
            ConfigSection.POSITION_SIZING.value: {
                "base_position_size_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 20.0,
                    "default": 10.0,
                    "description": "Base position size percentage"
                },
                "max_position_size_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 10.0,
                    "max_value": 50.0,
                    "default": 35.0,
                    "description": "Maximum position size percentage"
                },
                "trading_cash_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 70.0,
                    "max_value": 90.0,
                    "default": 80.0,
                    "description": "Percentage of capital for trading"
                },
                "cash_reserve_pct": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 10.0,
                    "max_value": 30.0,
                    "default": 20.0,
                    "description": "Percentage of capital reserved"
                },
                "agreement_medium_bonus": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.0,
                    "max_value": 1.0,
                    "default": 0.25,
                    "description": "Strategy agreement medium bonus"
                },
                "agreement_high_bonus": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.0,
                    "max_value": 1.0,
                    "default": 0.50,
                    "description": "Strategy agreement high bonus"
                },
                "agreement_maximum_bonus": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.0,
                    "max_value": 2.0,
                    "default": 1.00,
                    "description": "Strategy agreement maximum bonus"
                },
                "profit_scaling_200_pct_multiplier": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 3.0,
                    "default": 1.8,
                    "description": "Profit scaling multiplier for 200%+ profit"
                },
                "profit_scaling_100_pct_multiplier": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 2.5,
                    "default": 1.4,
                    "description": "Profit scaling multiplier for 100%+ profit"
                },
                "profit_scaling_50_pct_multiplier": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 2.0,
                    "default": 1.2,
                    "description": "Profit scaling multiplier for 50%+ profit"
                },
                "profit_scaling_25_pct_multiplier": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 1.5,
                    "default": 1.1,
                    "description": "Profit scaling multiplier for 25%+ profit"
                },
                "win_streak_enabled": {
                    "required": True,
                    "type": bool,
                    "default": True,
                    "description": "Enable win streak boosting"
                },
                "win_streak_base_multiplier": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 2.0,
                    "default": 1.0,
                    "description": "Base win streak multiplier"
                },
                "win_streak_max_multiplier": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 3.0,
                    "default": 2.0,
                    "description": "Maximum win streak multiplier"
                },
                "position_splitting_enabled": {
                    "required": True,
                    "type": bool,
                    "default": True,
                    "description": "Enable position splitting"
                },
                "include_current_positions": {
                    "required": True,
                    "type": bool,
                    "default": True,
                    "description": "Include current positions in available capital"
                },
                "ignore_manual_positions": {
                    "required": True,
                    "type": bool,
                    "default": True,
                    "description": "Ignore manual positions in available capital"
                }
            },
            ConfigSection.DATA.value: {
                "primary_provider": {
                    "required": True,
                    "type": str,
                    "allowed_values": ["etrade", "yahoo", "polygon", "alpha_vantage"],
                    "default": "etrade"
                },
                "cache_ttl_seconds": {
                    "required": True,
                    "type": int,
                    "min_value": 1,
                    "max_value": 3600,
                    "default": 300
                },
                "max_retries": {
                    "required": True,
                    "type": int,
                    "min_value": 1,
                    "max_value": 10,
                    "default": 3
                },
                "timeout_seconds": {
                    "required": True,
                    "type": int,
                    "min_value": 1,
                    "max_value": 300,
                    "default": 30
                }
            },
            ConfigSection.ETrade.value: {
                "consumer_key": {
                    "required": True,
                    "type": str,
                    "min_length": 10,
                    "max_length": 100,
                    "pattern": r"^[A-Za-z0-9_-]+$"
                },
                "consumer_secret": {
                    "required": True,
                    "type": str,
                    "min_length": 10,
                    "max_length": 100,
                    "pattern": r"^[A-Za-z0-9_-]+$"
                },
                "sandbox_mode": {
                    "required": True,
                    "type": bool,
                    "default": True
                },
                "api_base_url": {
                    "required": True,
                    "type": str,
                    "pattern": r"^https?://.*"
                }
            },
            ConfigSection.TELEGRAM.value: {
                "bot_token": {
                    "required": False,
                    "type": str,
                    "pattern": r"^\d+:[A-Za-z0-9_-]+$"
                },
                "chat_id": {
                    "required": False,
                    "type": str,
                    "pattern": r"^-?\d+$"
                },
                "enabled": {
                    "required": True,
                    "type": bool,
                    "default": False
                }
            },
            ConfigSection.STEALTH.value: {
                "breakeven_threshold": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.0001,
                    "max_value": 0.01,
                    "default": 0.005  # Optimized: 0.5% for better profit protection
                },
                "trailing_distance": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.0001,
                    "max_value": 0.10,
                    "default": 0.008  # Optimized: 0.8% for aggressive profit capture
                },
                "min_trailing_distance": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.0001,
                    "max_value": 0.01,
                    "default": 0.004  # Optimized: 0.4% minimum trailing
                },
                "max_trailing_distance": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.01,
                    "max_value": 0.10,
                    "default": 0.06  # Optimized: 6% maximum trailing
                },
                "volume_protection_threshold": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 1.0,
                    "max_value": 10.0,
                    "default": 2.0
                },
                "momentum_activation_threshold": {
                    "required": True,
                    "type": (int, float),
                    "min_value": 0.01,
                    "max_value": 0.1,
                    "default": 0.03  # Optimized: 3% momentum threshold
                }
            }
        }
    
    def load_and_validate_config(self) -> ConfigValidationResult:
        """Load and validate configuration from all sources"""
        try:
            # Load configuration from multiple sources
            self.config_data = self._load_config_from_sources()
            
            # Validate configuration
            validation_result = self.validate_configuration()
            
            if not validation_result.is_valid:
                log.error(f"❌ Configuration validation failed with {len(validation_result.errors)} errors")
                self._log_validation_errors(validation_result)
            else:
                log.info("✅ Configuration validation passed")
            
            return validation_result
            
        except Exception as e:
            log.error(f"❌ Configuration loading failed: {e}")
            return ConfigValidationResult(
                is_valid=False,
                errors=[ConfigError(
                    section=ConfigSection.GENERAL,
                    key="config_loading",
                    error_type=ConfigErrorType.INVALID,
                    message=f"Configuration loading failed: {e}",
                    severity="error"
                )]
            )
    
    def _load_config_from_sources(self) -> Dict[str, Any]:
        """Load configuration from multiple sources with priority order"""
        config_data = {}
        
        # 1. Load from environment variables
        env_config = self._load_from_environment()
        config_data.update(env_config)
        
        # 2. Load from config files
        file_config = self._load_from_files()
        config_data.update(file_config)
        
        # 3. Load defaults
        default_config = self._load_defaults()
        for section, rules in self.validation_rules.items():
            if section not in config_data:
                config_data[section] = {}
            for key, rule in rules.items():
                if key not in config_data[section] and "default" in rule:
                    config_data[section][key] = rule["default"]
        
        return config_data
    
    def _load_from_environment(self) -> Dict[str, Any]:
        """Load configuration from environment variables"""
        env_config = {}
        
        # Map environment variables to config sections
        env_mapping = {
            "ETRADE_CONSUMER_KEY": ("etrade", "consumer_key"),
            "ETRADE_CONSUMER_SECRET": ("etrade", "consumer_secret"),
            "ETRADE_SANDBOX_MODE": ("etrade", "sandbox_mode"),
            "TELEGRAM_BOT_TOKEN": ("telegram", "bot_token"),
            "TELEGRAM_CHAT_ID": ("telegram", "chat_id"),
            "TELEGRAM_ENABLED": ("telegram", "enabled"),
            "STRATEGY_MODE": ("general", "strategy_mode"),
            "INITIAL_CAPITAL": ("general", "initial_capital"),
            "MAX_POSITIONS": ("general", "max_positions"),
            "TRADING_ENABLED": ("general", "trading_enabled")
        }
        
        for env_var, (section, key) in env_mapping.items():
            value = os.getenv(env_var)
            if value is not None:
                if section not in env_config:
                    env_config[section] = {}
                
                # Convert value to appropriate type
                converted_value = self._convert_env_value(value, env_var)
                env_config[section][key] = converted_value
        
        return env_config
    
    def _convert_env_value(self, value: str, env_var: str) -> Any:
        """Convert environment variable value to appropriate type"""
        # Boolean conversion
        if env_var in ["ETRADE_SANDBOX_MODE", "TELEGRAM_ENABLED", "TRADING_ENABLED"]:
            return value.lower() in ["true", "1", "yes", "on"]
        
        # Numeric conversion
        if env_var in ["INITIAL_CAPITAL", "MAX_POSITIONS"]:
            try:
                return float(value) if "." in value else int(value)
            except ValueError:
                return value
        
        return value
    
    def _load_from_files(self) -> Dict[str, Any]:
        """Load configuration from files"""
        file_config = {}
        
        # Load from config.yaml
        yaml_path = self.config_path / "config.yaml"
        if yaml_path.exists():
            try:
                with open(yaml_path, 'r') as f:
                    yaml_config = yaml.safe_load(f)
                    if yaml_config:
                        file_config.update(yaml_config)
            except Exception as e:
                log.warning(f"Failed to load config.yaml: {e}")
        
        # Load from config.json
        json_path = self.config_path / "config.json"
        if json_path.exists():
            try:
                with open(json_path, 'r') as f:
                    json_config = json.load(f)
                    if json_config:
                        file_config.update(json_config)
            except Exception as e:
                log.warning(f"Failed to load config.json: {e}")
        
        return file_config
    
    def _load_defaults(self) -> Dict[str, Any]:
        """Load default configuration values"""
        defaults = {}
        
        for section, rules in self.validation_rules.items():
            defaults[section] = {}
            for key, rule in rules.items():
                if "default" in rule:
                    defaults[section][key] = rule["default"]
        
        return defaults
    
    def validate_configuration(self) -> ConfigValidationResult:
        """Validate configuration against rules"""
        errors = []
        warnings = []
        suggestions = []
        
        # Validate each section
        for section_name, section_rules in self.validation_rules.items():
            section_data = self.config_data.get(section_name, {})
            
            for key, rule in section_rules.items():
                # Check if required field is present
                if rule.get("required", False) and key not in section_data:
                    errors.append(ConfigError(
                        section=ConfigSection(section_name),
                        key=key,
                        error_type=ConfigErrorType.MISSING,
                        message=f"Required field '{key}' is missing from section '{section_name}'",
                        severity="error",
                        fix_suggestion=f"Add '{key}' to {section_name} configuration"
                    ))
                    continue
                
                # Skip validation if field is not present and not required
                if key not in section_data:
                    continue
                
                value = section_data[key]
                
                # Type validation
                if "type" in rule:
                    expected_type = rule["type"]
                    if isinstance(expected_type, tuple):
                        if not isinstance(value, expected_type):
                            errors.append(ConfigError(
                                section=ConfigSection(section_name),
                                key=key,
                                error_type=ConfigErrorType.INVALID,
                                message=f"Field '{key}' has invalid type. Expected {expected_type}, got {type(value)}",
                                current_value=value,
                                severity="error",
                                fix_suggestion=f"Convert '{key}' to {expected_type[0].__name__}"
                            ))
                    else:
                        if not isinstance(value, expected_type):
                            errors.append(ConfigError(
                                section=ConfigSection(section_name),
                                key=key,
                                error_type=ConfigErrorType.INVALID,
                                message=f"Field '{key}' has invalid type. Expected {expected_type.__name__}, got {type(value)}",
                                current_value=value,
                                severity="error",
                                fix_suggestion=f"Convert '{key}' to {expected_type.__name__}"
                            ))
                
                # Value range validation
                if isinstance(value, (int, float)):
                    if "min_value" in rule and value < rule["min_value"]:
                        errors.append(ConfigError(
                            section=ConfigSection(section_name),
                            key=key,
                            error_type=ConfigErrorType.OUT_OF_RANGE,
                            message=f"Field '{key}' value {value} is below minimum {rule['min_value']}",
                            current_value=value,
                            expected_value=rule["min_value"],
                            severity="error",
                            fix_suggestion=f"Set '{key}' to at least {rule['min_value']}"
                        ))
                    
                    if "max_value" in rule and value > rule["max_value"]:
                        errors.append(ConfigError(
                            section=ConfigSection(section_name),
                            key=key,
                            error_type=ConfigErrorType.OUT_OF_RANGE,
                            message=f"Field '{key}' value {value} exceeds maximum {rule['max_value']}",
                            current_value=value,
                            expected_value=rule["max_value"],
                            severity="error",
                            fix_suggestion=f"Set '{key}' to at most {rule['max_value']}"
                        ))
                
                # String length validation
                if isinstance(value, str):
                    if "min_length" in rule and len(value) < rule["min_length"]:
                        errors.append(ConfigError(
                            section=ConfigSection(section_name),
                            key=key,
                            error_type=ConfigErrorType.INVALID,
                            message=f"Field '{key}' length {len(value)} is below minimum {rule['min_length']}",
                            current_value=value,
                            severity="error",
                            fix_suggestion=f"Set '{key}' to at least {rule['min_length']} characters"
                        ))
                    
                    if "max_length" in rule and len(value) > rule["max_length"]:
                        errors.append(ConfigError(
                            section=ConfigSection(section_name),
                            key=key,
                            error_type=ConfigErrorType.INVALID,
                            message=f"Field '{key}' length {len(value)} exceeds maximum {rule['max_length']}",
                            current_value=value,
                            severity="error",
                            fix_suggestion=f"Set '{key}' to at most {rule['max_length']} characters"
                        ))
                
                # Allowed values validation
                if "allowed_values" in rule and value not in rule["allowed_values"]:
                    errors.append(ConfigError(
                        section=ConfigSection(section_name),
                        key=key,
                        error_type=ConfigErrorType.INVALID,
                        message=f"Field '{key}' value '{value}' is not in allowed values {rule['allowed_values']}",
                        current_value=value,
                        expected_value=rule["allowed_values"],
                        severity="error",
                        fix_suggestion=f"Set '{key}' to one of: {', '.join(map(str, rule['allowed_values']))}"
                    ))
        
        # Generate suggestions for optimization
        suggestions.extend(self._generate_optimization_suggestions())
        
        return ConfigValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions
        )
    
    def _generate_optimization_suggestions(self) -> List[str]:
        """Generate configuration optimization suggestions"""
        suggestions = []
        
        # Check for performance optimizations
        if self.config_data.get("data", {}).get("cache_ttl_seconds", 300) < 60:
            suggestions.append("Consider increasing cache_ttl_seconds to 300+ for better performance")
        
        if self.config_data.get("trading", {}).get("max_daily_trades", 20) > 50:
            suggestions.append("Consider reducing max_daily_trades to 20-30 for better risk management")
        
        # Check for security optimizations
        if self.config_data.get("etrade", {}).get("sandbox_mode", True) == False:
            suggestions.append("Ensure sandbox_mode is True for testing before live trading")
        
        # Check for risk management optimizations
        max_position_size = self.config_data.get("risk", {}).get("max_position_size", 0.1)
        if max_position_size > 0.2:
            suggestions.append("Consider reducing max_position_size to 0.1-0.15 for better risk management")
        
        return suggestions
    
    def _log_validation_errors(self, result: ConfigValidationResult):
        """Log configuration validation errors"""
        for error in result.errors:
            log.error(f"❌ {error.section.value}.{error.key}: {error.message}")
            if error.fix_suggestion:
                log.info(f"💡 Fix: {error.fix_suggestion}")
        
        for warning in result.warnings:
            log.warning(f"⚠️ {warning.section.value}.{warning.key}: {warning.message}")
        
        for suggestion in result.suggestions:
            log.info(f"💡 Suggestion: {suggestion}")
    
    def get_config_value(self, section: str, key: str, default: Any = None) -> Any:
        """Get configuration value with fallback to default"""
        return self.config_data.get(section, {}).get(key, default)
    
    def set_config_value(self, section: str, key: str, value: Any) -> bool:
        """Set configuration value with validation"""
        try:
            if section not in self.config_data:
                self.config_data[section] = {}
            
            # Validate the value before setting
            if section in self.validation_rules and key in self.validation_rules[section]:
                rule = self.validation_rules[section][key]
                
                # Basic type validation
                if "type" in rule:
                    expected_type = rule["type"]
                    if isinstance(expected_type, tuple):
                        if not isinstance(value, expected_type):
                            log.error(f"Invalid type for {section}.{key}: expected {expected_type}, got {type(value)}")
                            return False
                    else:
                        if not isinstance(value, expected_type):
                            log.error(f"Invalid type for {section}.{key}: expected {expected_type.__name__}, got {type(value)}")
                            return False
            
            self.config_data[section][key] = value
            log.info(f"✅ Configuration updated: {section}.{key} = {value}")
            return True
            
        except Exception as e:
            log.error(f"Failed to set configuration value {section}.{key}: {e}")
            return False
    
    def save_configuration(self, backup: bool = True) -> bool:
        """Save configuration to file"""
        try:
            if backup:
                self._create_backup()
            
            # Save to YAML file
            yaml_path = self.config_path / "config.yaml"
            with open(yaml_path, 'w') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, indent=2)
            
            # Save to JSON file
            json_path = self.config_path / "config.json"
            with open(json_path, 'w') as f:
                json.dump(self.config_data, f, indent=2)
            
            log.info("✅ Configuration saved successfully")
            return True
            
        except Exception as e:
            log.error(f"Failed to save configuration: {e}")
            return False
    
    def _create_backup(self):
        """Create configuration backup"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"config_backup_{timestamp}.json"
            
            with open(backup_path, 'w') as f:
                json.dump(self.config_data, f, indent=2)
            
            log.info(f"✅ Configuration backup created: {backup_path}")
            
        except Exception as e:
            log.warning(f"Failed to create configuration backup: {e}")
    
    def restore_configuration(self, backup_path: str) -> bool:
        """Restore configuration from backup"""
        try:
            with open(backup_path, 'r') as f:
                backup_data = json.load(f)
            
            # Validate backup data
            temp_config = self.config_data.copy()
            self.config_data = backup_data
            
            validation_result = self.validate_configuration()
            
            if validation_result.is_valid:
                log.info(f"✅ Configuration restored from {backup_path}")
                return True
            else:
                # Restore original config
                self.config_data = temp_config
                log.error(f"❌ Backup configuration is invalid: {backup_path}")
                return False
                
        except Exception as e:
            log.error(f"Failed to restore configuration from {backup_path}: {e}")
            return False
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get configuration summary for reporting"""
        return {
            "total_sections": len(self.config_data),
            "total_keys": sum(len(section) for section in self.config_data.values()),
            "validation_level": self.validation_level.value,
            "last_validation": datetime.now().isoformat(),
            "sections": {
                section: {
                    "key_count": len(keys),
                    "keys": list(keys.keys())
                }
                for section, keys in self.config_data.items()
            }
        }

# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_config() -> PrimeSettingsConfiguration:
    """Get global configuration instance"""
    global _config_instance
    if '_config_instance' not in globals():
        _config_instance = PrimeSettingsConfiguration()
    return _config_instance

def validate_config() -> ConfigValidationResult:
    """Validate current configuration"""
    config = get_config()
    return config.validate_configuration()

def get_config_value(section: str, key: str, default: Any = None) -> Any:
    """Get configuration value"""
    config = get_config()
    return config.get_config_value(section, key, default)

def set_config_value(section: str, key: str, value: Any) -> bool:
    """Set configuration value"""
    config = get_config()
    return config.set_config_value(section, key, value)

# Global configuration instance
_config_instance = None

if __name__ == "__main__":
    # Test configuration validation
    config = PrimeSettingsConfiguration()
    result = config.validate_configuration()
    
    print(f"Configuration validation: {'PASS' if result.is_valid else 'FAIL'}")
    print(f"Errors: {len(result.errors)}")
    print(f"Warnings: {len(result.warnings)}")
    print(f"Suggestions: {len(result.suggestions)}")
    
    if result.errors:
        print("\nErrors:")
        for error in result.errors:
            print(f"  - {error.section.value}.{error.key}: {error.message}")
    
    if result.suggestions:
        print("\nSuggestions:")
        for suggestion in result.suggestions:
            print(f"  - {suggestion}")
