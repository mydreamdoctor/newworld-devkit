/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 */

#pragma once

#include <AzCore/Component/Component.h>
#include <AzCore/Component/TickBus.h>
#include <AzCore/Math/Color.h>

namespace NWLighting
{
    //! Serialized New World environment settings for one level.
    //!
    //! The values are produced by the level import (nwenv.py reads the
    //! game's mission_mission0.xml environment block) and applied by
    //! NWEnvironmentComponent.
    class NWEnvironmentConfig final
    {
    public:
        AZ_TYPE_INFO(NWEnvironmentConfig, "{4EEF6022-E6E9-474A-9C4E-2AB64287068D}");
        AZ_CLASS_ALLOCATOR(NWEnvironmentConfig, AZ::SystemAllocator);

        static void Reflect(AZ::ReflectContext* context);

        //! Directional sun light.
        AZ::Color m_sunColor = AZ::Color(1.0f, 0.96f, 0.88f, 1.0f);
        float m_sunIntensity = 2.5f;

        //! Hemisphere ambient: sky colour from above, ground bounce from below.
        AZ::Color m_skyColor = AZ::Color(0.42f, 0.56f, 0.78f, 1.0f);
        AZ::Color m_groundColor = AZ::Color(0.28f, 0.24f, 0.19f, 1.0f);
        float m_ambientIntensity = 0.35f;

        //! Deferred fog.
        bool m_applyFog = false;
        AZ::Color m_fogColor = AZ::Color(0.72f, 0.76f, 0.82f, 1.0f);
        float m_fogStartDistance = 40.0f;
        float m_fogEndDistance = 400.0f;

        //! Image based light exposure on the same entity, when present.
        float m_iblExposure = 1.0f;
    };

    //! Applies a New World environment to the Atom scene.
    //!
    //! Drives the sibling DirectionalLightComponent (colour/intensity),
    //! adds a two-light hemisphere ambient (sky above, ground below,
    //! shadows off), and optionally configures deferred fog. This gives
    //! the game's light balance without any per-level manual tuning.
    class NWEnvironmentComponent final
        : public AZ::Component
        , private AZ::TickBus::Handler
    {
    public:
        AZ_COMPONENT(NWEnvironmentComponent, "{9ACB9419-4293-4CC4-AE23-1A980B1E8373}");

        static void Reflect(AZ::ReflectContext* context);
        static void GetProvidedServices(AZ::ComponentDescriptor::DependencyArrayType& provided);
        static void GetIncompatibleServices(AZ::ComponentDescriptor::DependencyArrayType& incompatible);
        static void GetRequiredServices(AZ::ComponentDescriptor::DependencyArrayType& required);

        NWEnvironmentComponent() = default;
        explicit NWEnvironmentComponent(const NWEnvironmentConfig& config);

        // AZ::Component overrides
        void Activate() override;
        void Deactivate() override;

        void SetConfiguration(const NWEnvironmentConfig& config);
        const NWEnvironmentConfig& GetConfiguration() const;

        // AZ::TickBus overrides
        void OnTick(float deltaTime, AZ::ScriptTimePoint time) override;

    private:
        void ApplyConfiguration();

        NWEnvironmentConfig m_config;
    };
} // namespace NWLighting
